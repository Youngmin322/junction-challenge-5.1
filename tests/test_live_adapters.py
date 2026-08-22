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
        assert float(params["ymin"]) == 36.95
        assert float(params["xmax"]) == 129.52
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
