from datetime import UTC, datetime

import httpx
import pytest

from jellyguard.config.settings import Settings
from jellyguard.domain import source_state
from jellyguard.domain.source_state import PublicDataClient

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
    record = current.fetch("nifs_jelly_catalog")
    assert calls == 2
    assert record["rows_received"] == 0


def test_khoa_live_budget_stops_before_upstream_call(tmp_path):
    current = client(tmp_path, khoa_key="secret", live_budget_s=-1)
    with pytest.raises(TimeoutError, match="budget"):
        current.fetch("khoa_tw_recent_hanul")


@pytest.mark.parametrize("source_id", ["unknown", "khoa_roms_live"])
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
