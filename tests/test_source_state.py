import json
from datetime import UTC, datetime, timedelta

import pytest

from jellyguard.composition import create_service
from jellyguard.config.registry import SOURCE_REGISTRY
from jellyguard.config.settings import Settings
from jellyguard.contracts import DataMode
from jellyguard.domain.source_state import SourceCache, SourceResolver, SourceState

NOW = datetime(2026, 8, 23, 2, 0, tzinfo=UTC)


def fixture_record(source_id, fetched_at=None, payload=None):
    return {
        "source_id": source_id,
        "fetched_at": fetched_at,
        "issued_at": None,
        "license": "public-data",
        "payload": payload or [{"id": 1}],
    }


def resolver(tmp_path, **settings_overrides):
    settings = Settings(
        _env_file=None,
        blob_root=tmp_path / "runs",
        cache_root=tmp_path / "cache",
        cassette_root=tmp_path / "cassettes",
        **settings_overrides,
    )
    fixtures = {
        "historical_observation_fixture": {
            **fixture_record("historical_observation_fixture"),
            "fixture_checksum": "fixture",
        },
        "nifs_jelly_catalog": {
            **fixture_record("nifs_jelly_catalog", "2026-08-20T00:00:00Z"),
            "fixture_checksum": "fixture",
        },
        "khoa_tw_recent_hanul": {
            **fixture_record("khoa_tw_recent_hanul"),
            "fixture_checksum": "fixture",
        },
        "synthetic_field": fixture_record("synthetic_field"),
    }
    return SourceResolver(settings, lambda: NOW, fixtures)


@pytest.mark.parametrize("source_id", sorted(SOURCE_REGISTRY))
def test_every_source_rejects_an_unsupported_mode(tmp_path, source_id):
    definition = SOURCE_REGISTRY[source_id]
    unsupported = (
        next(mode for mode in DataMode if mode not in definition.modes)
        if len(definition.modes) < len(DataMode)
        else None
    )
    if unsupported is None:
        pytest.skip("source supports every mode")
    result = resolver(tmp_path).resolve(source_id, [unsupported])
    assert result.state == SourceState.NOT_REQUESTED
    assert result.public_reason_code == "MODE_NOT_ALLOWED"


@pytest.mark.parametrize(
    ("source_id", "expected"),
    [
        ("historical_observation_fixture", SourceState.CACHED_FIXTURE),
        ("nifs_jelly_catalog", SourceState.CACHED_FIXTURE),
        ("khoa_tw_recent_hanul", SourceState.CACHED_FIXTURE),
        ("cached_field", SourceState.CACHE_MISS),
        ("khoa_roms_blocked_fixture", SourceState.CACHE_MISS),
        ("nifs_redtide_list", SourceState.CACHE_MISS),
        ("nifs_soo_list", SourceState.CACHE_MISS),
        ("khoa_hf_current_regression", SourceState.CACHE_MISS),
    ],
)
def test_fixture_cached_resolution(tmp_path, source_id, expected):
    assert resolver(tmp_path).resolve(source_id, [DataMode.CACHED]).state == expected


@pytest.mark.parametrize(
    "source_id",
    [
        "nifs_jelly_catalog",
        "khoa_tw_recent_hanul",
        "nifs_redtide_list",
        "nifs_soo_list",
        "khoa_roms_live",
    ],
)
def test_live_without_configuration_has_one_public_reason(tmp_path, source_id):
    current = resolver(
        tmp_path,
        source_mode="live",
        live_enabled_sources=source_id,
    )
    result = current.resolve(source_id, [DataMode.LIVE])
    assert result.state == SourceState.LIVE_UNCONFIGURED
    assert result.public_reason_code == "LIVE_NOT_ENABLED"
    assert result.public_reason == "이 실행 프로필에서 LIVE 연결이 활성화되지 않음"


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    [
        (10 * 86400, SourceState.CACHED_FRESH),
        (10 * 86400 + 1, SourceState.CACHED_STALE),
        (45 * 86400, SourceState.CACHED_STALE),
        (45 * 86400 + 1, SourceState.CACHED_EXPIRED),
    ],
)
def test_nifs_freshness_boundaries(tmp_path, age_seconds, expected):
    current = resolver(tmp_path)
    record = fixture_record(
        "nifs_jelly_catalog",
        (NOW - timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z"),
    )
    SourceCache(current.settings.cache_root).append(record)
    assert current.resolve("nifs_jelly_catalog", [DataMode.CACHED]).state == expected


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    [
        (3 * 3600, SourceState.CACHED_FRESH),
        (3 * 3600 + 1, SourceState.CACHED_STALE),
        (24 * 3600, SourceState.CACHED_STALE),
        (24 * 3600 + 1, SourceState.CACHED_EXPIRED),
    ],
)
def test_khoa_freshness_boundaries(tmp_path, age_seconds, expected):
    current = resolver(tmp_path)
    record = fixture_record(
        "khoa_tw_recent_hanul",
        (NOW - timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z"),
    )
    SourceCache(current.settings.cache_root).append(record)
    assert current.resolve("khoa_tw_recent_hanul", [DataMode.CACHED]).state == expected


def test_cache_without_provider_timestamp_is_not_fresh(tmp_path):
    current = resolver(tmp_path)
    SourceCache(current.settings.cache_root).append(fixture_record("nifs_jelly_catalog"))
    result = current.resolve("nifs_jelly_catalog", [DataMode.CACHED])
    assert result.state == SourceState.CACHED_UNKNOWN_AGE
    assert result.public_reason_code == "UNKNOWN_AGE"
    assert result.age_seconds is None


@pytest.mark.parametrize(
    ("issued_at", "expected"),
    [
        (NOW.isoformat().replace("+00:00", "Z"), SourceState.LIVE_OK),
        (
            (NOW - timedelta(days=20)).isoformat().replace("+00:00", "Z"),
            SourceState.LIVE_STALE,
        ),
        (
            (NOW - timedelta(days=60)).isoformat().replace("+00:00", "Z"),
            SourceState.LIVE_EXPIRED,
        ),
        (None, SourceState.LIVE_UNKNOWN_AGE),
    ],
)
def test_live_freshness_uses_provider_timestamp(tmp_path, monkeypatch, issued_at, expected):
    current = resolver(
        tmp_path,
        source_mode="live",
        live_enabled_sources="nifs_jelly_catalog",
        nifs_jelly_key="configured",
    )
    record = {
        **fixture_record("nifs_jelly_catalog", NOW.isoformat().replace("+00:00", "Z")),
        "issued_at": issued_at,
        "adapter_version": "test-live",
        "request_fingerprint": "f" * 64,
        "content_checksum": "c" * 64,
        "rows_received": 1,
        "pages_received": 1,
        "partial": False,
        "failed_pages": [],
    }
    monkeypatch.setattr(current.client, "fetch", lambda _source_id: record)
    assert current.resolve("nifs_jelly_catalog", [DataMode.LIVE]).state == expected


def test_enabled_but_unimplemented_live_source_is_reported_without_throwing(tmp_path):
    current = resolver(
        tmp_path,
        source_mode="live",
        live_enabled_sources="nifs_jelly_detail2_unverified",
        nifs_jelly_key="configured",
    )
    result = current.resolve("nifs_jelly_detail2_unverified", [DataMode.LIVE])
    assert result.state == SourceState.LIVE_UNSUPPORTED
    assert result.public_reason_code == "LIVE_NOT_ENABLED"


def test_roms_live_resolves_when_enabled_and_stays_disabled_otherwise(tmp_path, monkeypatch):
    record = {
        "source_id": "khoa_roms_live",
        "issued_at": "2026-08-23T01:00:00Z",
        "fetched_at": "2026-08-23T02:00:00Z",
        "content_checksum": "sha",
        "request_fingerprint": "fp",
        "redacted_endpoint": "https://apis.data.go.kr/1192136/roms/GetRomsApiService",
        "adapter_version": "public-data-v1",
        "license": "public-data",
        "payload": [{"lat": 37.0, "lon": 129.4, "crdir_convention": "UNVERIFIED"}],
        "rows_received": 1,
        "pages_received": 1,
        "partial": False,
        "failed_pages": [],
    }
    enabled = resolver(
        tmp_path,
        source_mode="live",
        live_enabled_sources="khoa_roms_live",
        khoa_key="configured",
    )
    monkeypatch.setattr(enabled.client, "fetch", lambda _source_id: record)
    assert enabled.resolve("khoa_roms_live", [DataMode.LIVE]).state == SourceState.LIVE_OK

    default = resolver(tmp_path, khoa_key="configured")
    assert default.resolve("khoa_roms_live", [DataMode.LIVE]).state == SourceState.LIVE_DISABLED


def test_synthetic_is_only_selected_explicitly(tmp_path):
    current = resolver(tmp_path)
    assert current.resolve("synthetic_field", [DataMode.CACHED]).state == SourceState.NOT_REQUESTED
    assert (
        current.resolve("synthetic_field", [DataMode.SYNTHETIC]).state
        == SourceState.SYNTHETIC_EXPLICIT
    )


def test_live_failure_never_falls_into_synthetic(tmp_path, monkeypatch):
    current = resolver(
        tmp_path,
        source_mode="live",
        live_enabled_sources="nifs_jelly_catalog",
        nifs_jelly_key="configured",
    )

    def unavailable(_source_id):
        raise TimeoutError

    monkeypatch.setattr(current.client, "fetch", unavailable)
    result = current.resolve("nifs_jelly_catalog", [DataMode.LIVE, DataMode.SYNTHETIC])
    assert result.state == SourceState.LIVE_UNAVAILABLE
    assert result.data_mode is None


def test_live_success_is_cached_and_reusable(tmp_path, monkeypatch):
    current = resolver(
        tmp_path,
        source_mode="live",
        live_enabled_sources="nifs_jelly_catalog",
        nifs_jelly_key="configured",
    )
    record = {
        **fixture_record("nifs_jelly_catalog", NOW.isoformat().replace("+00:00", "Z")),
        "request_fingerprint": "fingerprint",
        "http_status": 200,
        "provider_result_code": "00",
        "content_checksum": "checksum",
        "adapter_version": "test",
        "rows_received": 1,
        "pages_received": 1,
        "partial": False,
        "failed_pages": [],
        "issued_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    monkeypatch.setattr(current.client, "fetch", lambda _source_id: record)
    live = current.resolve("nifs_jelly_catalog", [DataMode.LIVE])
    assert live.state == SourceState.LIVE_OK
    assert current.cache.latest("nifs_jelly_catalog")["payload"] == [{"id": 1}]


def test_cassette_mode_reads_committed_shape(tmp_path):
    current = resolver(tmp_path, source_mode="cassette")
    current.settings.cassette_root.mkdir(parents=True)
    record = fixture_record("nifs_jelly_catalog", NOW.isoformat().replace("+00:00", "Z"))
    (current.settings.cassette_root / "nifs_jelly_catalog.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    result = current.resolve("nifs_jelly_catalog", [DataMode.CACHED])
    assert result.state == SourceState.CACHED_FRESH
    assert result.payload == [{"id": 1}]


def test_source_status_never_throws_when_all_keys_are_missing(tmp_path):
    current = create_service(
        Settings(
            _env_file=None,
            source_mode="live",
            live_enabled_sources="nifs_jelly_catalog,khoa_tw_recent_hanul,khoa_roms_live",
            blob_root=tmp_path / "runs",
            cache_root=tmp_path / "cache",
        ),
        clock=lambda: NOW,
    )
    result = current.get_source_status(allowed_modes=["LIVE", "CACHED", "SYNTHETIC"])
    assert result.status in {"READY", "DEGRADED", "STALE"}
    assert len(result.data["sources"]) == len(SOURCE_REGISTRY)
