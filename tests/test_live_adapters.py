from datetime import UTC, datetime

import httpx
import pytest

from jellyguard.config.settings import Settings
from jellyguard.domain import source_state
from jellyguard.domain.source_state import ProviderNoDataError, PublicDataClient

NOW = datetime(2026, 8, 23, 2, 0, tzinfo=UTC)


def client(tmp_path, **overrides):
    return PublicDataClient(
        Settings(_env_file=None, blob_root=tmp_path, **overrides),
        lambda: NOW,
    )


@pytest.mark.parametrize("single_item", [False, True])
def test_nifs_jelly_list_normalizes_list_and_single_item(tmp_path, monkeypatch, single_item):
    item = {"board_idx": "A1", "board_subject": "주간보고", "inpt_date": "2026-08-20"}
    payload_item = item if single_item else [item, {**item, "board_idx": "A2"}]

    def handler(request):
        assert request.url.params["id"] == "jellyList"
        assert "key" in request.url.params
        return httpx.Response(
            200,
            json={"header": {"resultCode": "00"}, "body": {"item": payload_item}},
        )

    current = client(tmp_path, nifs_jelly_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    record = current.fetch("nifs_jelly_catalog")
    assert record["rows_received"] == (1 if single_item else 2)
    assert record["payload"][0]["claim_type"] == "context/report_catalog"
    assert record["issued_at"] == "2026-08-20T00:00:00Z"
    assert record["request_spec"]["dataset_id"] == "jellyList"
    assert "key" not in record["request_spec"]
    assert "secret" not in record["redacted_endpoint"]


@pytest.mark.parametrize("status_code", [401, 403])
def test_nifs_http_auth_failure_is_classified(tmp_path, monkeypatch, status_code):
    current = client(tmp_path, nifs_jelly_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(status_code))
        ),
    )
    with pytest.raises(PermissionError):
        current.fetch("nifs_jelly_catalog")


@pytest.mark.parametrize("result_code", ["01", "02", "03", "10", "20", "30"])
def test_nifs_provider_auth_codes_are_classified(tmp_path, monkeypatch, result_code):
    current = client(tmp_path, nifs_jelly_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, json={"header": {"resultCode": result_code}, "body": {}}
                )
            )
        ),
    )
    with pytest.raises(PermissionError):
        current.fetch("nifs_jelly_catalog")


def test_nifs_invalid_item_shape_is_rejected(tmp_path, monkeypatch):
    current = client(tmp_path, nifs_jelly_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"header": {"resultCode": "00"}, "body": {"item": "invalid"}},
                )
            )
        ),
    )
    with pytest.raises(TypeError):
        current.fetch("nifs_jelly_catalog")


def test_khoa_three_public_stations_are_normalized(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        code = request.url.params["obsCode"]
        seen.append(code)
        return httpx.Response(
            200,
            json={
                "header": {"resultCode": "00"},
                "body": {
                    "items": {
                        "item": {
                            "obsvtrNm": code,
                            "lat": 37.1,
                            "lot": 129.4,
                            "obsrvnDt": "2026-08-23 10:50",
                            "crdir": 200,
                            "crsp": 5,
                            "wtem": 24,
                        }
                    }
                },
            },
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    record = current.fetch("khoa_tw_recent_hanul")
    assert seen == ["HB_0007", "HB_0008", "HB_0009"]
    assert record["rows_received"] == 3
    assert record["issued_at"] == "2026-08-23T01:50:00Z"
    assert record["request_spec"] == {"station_codes": ["HB_0007", "HB_0008", "HB_0009"]}
    assert all(row["crdir_convention"] == "UNVERIFIED" for row in record["payload"])


def test_transient_server_failure_is_retried_once(tmp_path, monkeypatch):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"header": {"resultCode": "00"}, "body": {"item": []}},
        )

    current = client(tmp_path, nifs_jelly_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(source_state.time, "sleep", lambda _seconds: None)
    with pytest.raises(ProviderNoDataError):
        current.fetch("nifs_jelly_catalog")
    assert calls == 2


@pytest.mark.parametrize(
    ("result_code", "expected_exception"),
    [
        ("20", PermissionError),
        ("03", ProviderNoDataError),
        ("99", ValueError),
    ],
)
def test_khoa_provider_result_codes_are_not_all_auth_failures(
    tmp_path, monkeypatch, result_code, expected_exception
):
    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"header": {"resultCode": result_code}, "body": {}},
                )
            )
        ),
    )
    with pytest.raises(expected_exception):
        current.fetch("khoa_tw_recent_hanul")


def test_khoa_live_budget_stops_before_upstream_call(tmp_path):
    current = client(tmp_path, khoa_key="secret", live_budget_s=-1)
    with pytest.raises(TimeoutError, match="budget"):
        current.fetch("khoa_tw_recent_hanul")


@pytest.mark.parametrize("source_id", ["unknown", "nifs_jelly_detail2_unverified"])
def test_unimplemented_live_source_is_not_silently_reinterpreted(tmp_path, source_id):
    with pytest.raises(LookupError):
        client(tmp_path).fetch(source_id)


@pytest.mark.parametrize(
    ("source_id", "dataset_id", "key_name"),
    [
        ("nifs_redtide_list", "redtideList", "nifs_redtide_key"),
        ("nifs_soo_list", "sooList", "nifs_soo_key"),
    ],
)
def test_optional_nifs_context_is_preserved_as_context(
    tmp_path, monkeypatch, source_id, dataset_id, key_name
):
    def handler(request):
        assert request.url.params["id"] == dataset_id
        return httpx.Response(
            200,
            json={
                "header": {"resultCode": "00"},
                "body": {"item": {"idx": "A1", "obs_dat": "20260820", "value": 24}},
            },
        )

    current = client(tmp_path, **{key_name: "secret"})
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    record = current.fetch(source_id)
    assert record["rows_received"] == 1
    assert record["payload"][0]["claim_type"] == "context"
    assert record["payload"][0]["raw"]["value"] == 24


def _roms_item(lat, lon, hour):
    return {
        "predcDt": f"2026-08-22 {hour:02d}:00:00",
        "lat": lat,
        "lot": lon,
        "crdir": 4.91,
        "crsp": 0.15,
        "wtem": 24.99,
    }


def _roms_pages(cells, hours):
    rows = [_roms_item(lat, lon, hour) for lat, lon in cells for hour in range(hours)]
    return rows


def test_khoa_roms_pages_until_total_count_and_summarizes_grid(tmp_path, monkeypatch):
    cells = [(36.99046, 129.43565), (36.99046, 129.46762), (37.01840, 129.43565)]
    rows = _roms_pages(cells, hours=4)
    page_size = 5

    def handler(request):
        params = request.url.params
        assert params["type"] == "json"
        assert float(params["ymin"]) == 36.90
        assert float(params["xmax"]) == 129.57
        page_no = int(params["pageNo"])
        chunk = rows[(page_no - 1) * page_size : page_no * page_size]
        return httpx.Response(
            200,
            json={
                "header": {"resultCode": "00"},
                "body": {"items": {"item": chunk}, "totalCount": len(rows)},
            },
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(current, "ROMS_PAGE_SIZE", page_size)
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    record = current.fetch("khoa_roms_live")

    assert record["rows_received"] == len(rows)
    assert record["rows_expected"] == len(rows)
    assert record["partial"] is False
    assert record["pages_received"] == 3
    assert "secret" not in record["redacted_endpoint"]
    assert "serviceKey" not in record["request_spec"]

    summary = record["grid_summary"]
    assert summary["is_area_field"] is True
    assert summary["cell_count"] == 3
    assert summary["timestep_count"] == 4
    assert summary["depth_class"] == "surface_only"
    assert summary["crdir_convention"] == "UNVERIFIED"
    assert record["payload"][0]["crdir_convention"] == "UNVERIFIED"
    # The provider never publishes a model run time, so the age must stay unknown
    # rather than being inferred from the first forecast hour.
    assert record["issued_at"] is None
    assert summary["issue_time_published"] is False
    assert summary["valid_from_local"] == "2026-08-22 00:00:00"


def test_khoa_roms_single_cell_is_not_reported_as_area_field(tmp_path, monkeypatch):
    rows = _roms_pages([(36.99046, 129.43565)], hours=2)

    def handler(_request):
        return httpx.Response(
            200,
            json={
                "header": {"resultCode": "00"},
                "body": {"items": {"item": rows}, "totalCount": len(rows)},
            },
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    summary = current.fetch("khoa_roms_live")["grid_summary"]
    assert summary["is_area_field"] is False
    assert summary["cell_count"] == 1
    assert summary["lat_spacing_deg"] is None


def test_khoa_roms_truncated_read_is_marked_partial(tmp_path, monkeypatch):
    rows = _roms_pages([(36.99046, 129.43565), (37.01840, 129.43565)], hours=3)

    def handler(request):
        page_no = int(request.url.params["pageNo"])
        chunk = rows[(page_no - 1) * 2 : page_no * 2] if page_no <= 2 else []
        return httpx.Response(
            200,
            json={
                "header": {"resultCode": "00"},
                "body": {"items": {"item": chunk}, "totalCount": len(rows)},
            },
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(current, "ROMS_PAGE_SIZE", 2)
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    record = current.fetch("khoa_roms_live")
    assert record["partial"] is True
    assert record["rows_received"] < record["rows_expected"]


@pytest.mark.parametrize("result_code", ["20", "30"])
def test_khoa_roms_provider_auth_codes_are_permission_errors(tmp_path, monkeypatch, result_code):
    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"header": {"resultCode": result_code}})
            )
        ),
    )
    with pytest.raises(PermissionError):
        current.fetch("khoa_roms_live")


def test_khoa_roms_no_data_code_raises_provider_no_data(tmp_path, monkeypatch):
    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"header": {"resultCode": "03"}})
            )
        ),
    )
    with pytest.raises(ProviderNoDataError):
        current.fetch("khoa_roms_live")


def test_khoa_crnt_fcst_preserves_textual_direction_and_unverified_units(tmp_path, monkeypatch):
    def handler(request):
        params = request.url.params
        assert params["obsCode"] == "16LTC14"
        assert len(params["date"]) == 8
        return httpx.Response(
            200,
            json={
                "header": {"resultCode": "00"},
                "body": {
                    "items": {
                        "item": [
                            {
                                "obsvtrNm": "울산신항",
                                "lat": 35.4165,
                                "lot": 129.3991,
                                "predcDt": "2026-08-23 00:00",
                                "crdir": "서남서",
                                "crsp": 10.03,
                            }
                        ]
                    }
                },
            },
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    record = current.fetch("khoa_crnt_fcst_reference")
    row = record["payload"][0]

    # The provider returns a compass name, not degrees, and an undocumented speed unit.
    assert row["current_direction_text"] == "서남서"
    assert row["crdir_format"] == "korean_16point_text"
    assert row["crsp_unit"] == "UNVERIFIED"
    assert row["crdir_convention"] == "UNVERIFIED"
    # No issue time is published, so the age must stay unknown.
    assert record["issued_at"] is None
    assert record["reference_only"] is True
    assert record["request_spec"]["obs_code"] == "16LTC14"


def _hf_item(name, lat, lon, crdir=200.0, crsp=5.0, observed_at="2026-08-23 06:00"):
    return {
        "obsvtrNm": name,
        "lat": lat,
        "lot": lon,
        "obsrvnDt": observed_at,
        "crdir": crdir,
        "crsp": crsp,
    }


def test_khoa_hf_current_sweeps_all_13_known_stations(tmp_path, monkeypatch):
    from jellyguard.domain.source_state import PublicDataClient

    seen = []

    def handler(request):
        code = request.url.params["obsCode"]
        seen.append(code)
        assert request.url.params["numOfRows"] == "1"
        return httpx.Response(
            200,
            json={
                "header": {"resultCode": "00"},
                "body": {"items": {"item": _hf_item(code, 36.0, 129.4)}},
            },
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    record = current.fetch("khoa_hf_current_reference")
    assert seen == list(PublicDataClient.HF_STATION_CODES)
    assert len(seen) == 13
    assert record["rows_received"] == 13
    assert record["reference_only"] is True
    assert all(row["crdir_convention"] == "UNVERIFIED" for row in record["payload"])
    assert all(row["distance_to_wolsong_km"] is not None for row in record["payload"])


def test_khoa_hf_current_null_observation_station_is_kept_not_dropped(tmp_path, monkeypatch):
    """HF_0073 (동해남부) has been observed live to answer with resultCode 00 but
    crdir/crsp reported as null. The batch must keep that row -- a null observation
    is still a station that answered, not a reason to make it vanish."""

    def handler(request):
        code = request.url.params["obsCode"]
        if code == "HF_0073":
            item = _hf_item(code, 36.42, 129.66, crdir=None, crsp=None)
        else:
            item = _hf_item(code, 36.0, 129.4)
        return httpx.Response(
            200, json={"header": {"resultCode": "00"}, "body": {"items": {"item": item}}}
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    record = current.fetch("khoa_hf_current_reference")
    assert record["rows_received"] == 13
    null_row = next(row for row in record["payload"] if row["station_code"] == "HF_0073")
    assert null_row["current_direction"] is None
    assert null_row["current_speed"] is None
    # A null observation still carries a real position, so distance is still computable.
    assert null_row["distance_to_wolsong_km"] is not None


@pytest.mark.parametrize("result_code", ["20", "30", "31", "32"])
def test_khoa_hf_current_provider_auth_codes_are_permission_errors(
    tmp_path, monkeypatch, result_code
):
    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"header": {"resultCode": result_code}})
            )
        ),
    )
    with pytest.raises(PermissionError):
        current.fetch("khoa_hf_current_reference")


@pytest.mark.parametrize("status_code", [401, 403])
def test_khoa_hf_current_http_auth_failure_is_classified(tmp_path, monkeypatch, status_code):
    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(status_code))
        ),
    )
    with pytest.raises(PermissionError):
        current.fetch("khoa_hf_current_reference")


def test_khoa_hf_current_distance_to_wolsong_matches_haversine_math(tmp_path, monkeypatch):
    """Pohang harbour (HF_0071) is at lat 36.01926, lon 129.44425 (live-probed).
    Wolsong is at lat 35.7146, lon 129.4750. Deriving the great-circle distance
    directly (not just trusting the adapter) with R = 6371.0088 km gives ~34 km --
    the closest of any live HF station to a Gyeongbuk plant. Hanul is excluded from
    this field: the closest live HF station to Hanul is 71 km away, so a
    distance-to-Hanul figure here would never point at anything actionable."""
    from math import asin, cos, radians, sin, sqrt

    def expected_km(lat1, lon1, lat2, lon2):
        r = 6371.0088
        p1, p2 = radians(lat1), radians(lat2)
        dphi = radians(lat2 - lat1)
        dlambda = radians(lon2 - lon1)
        a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
        return 2 * r * asin(sqrt(a))

    pohang_lat, pohang_lon = 36.01926, 129.44425
    expected = expected_km(pohang_lat, pohang_lon, 35.7146, 129.4750)
    assert 30 < expected < 38

    def handler(request):
        code = request.url.params["obsCode"]
        if code == "HF_0071":
            item = _hf_item(code, pohang_lat, pohang_lon)
        else:
            item = _hf_item(code, 36.0, 129.4)
        return httpx.Response(
            200, json={"header": {"resultCode": "00"}, "body": {"items": {"item": item}}}
        )

    current = client(tmp_path, khoa_key="secret")
    monkeypatch.setattr(
        current,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    record = current.fetch("khoa_hf_current_reference")
    pohang_row = next(row for row in record["payload"] if row["station_code"] == "HF_0071")
    assert pohang_row["distance_to_wolsong_km"] == round(expected, 1)
    assert "distance_to_hanul_km" not in pohang_row


def test_khoa_hf_current_live_budget_stops_before_upstream_call(tmp_path):
    current = client(tmp_path, khoa_key="secret", live_budget_s=-1)
    with pytest.raises(TimeoutError, match="budget"):
        current.fetch("khoa_hf_current_reference")
