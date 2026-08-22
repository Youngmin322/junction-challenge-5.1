from __future__ import annotations

import ast
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jellyguard.composition import create_service
from jellyguard.config.registry import SOURCE_REGISTRY
from jellyguard.config.settings import Settings
from jellyguard.contracts.models import RawPayload

FIXED_NOW = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)


def service():
    counter = 0

    def new_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-TEST-{counter:04d}"

    return create_service(
        Settings(_env_file=None, blob_root=Path(tempfile.mkdtemp(prefix="jellyguard-test-"))),
        clock=lambda: FIXED_NOW,
        new_id=new_id,
    )


def test_registry_contains_approved_twelve_sources():
    assert len(SOURCE_REGISTRY) == 12
    assert "nifs_jelly_catalog" in SOURCE_REGISTRY
    assert "khoa_roms_blocked_fixture" in SOURCE_REGISTRY


def test_catalog_is_context_only_and_has_no_observation_fields():
    result = service().search_observations(allowed_modes=["CACHED"])
    catalog = result.data["catalog_context"]["items"][0]
    assert "geometry" not in catalog
    assert "density" not in catalog
    assert "count" not in catalog
    assert result.data["records"][0]["claim_type"] == "direct_observation"
    selected = result.selected_sources[0]
    assert len(selected["content_checksum"]) == 64
    assert len(selected["request_fingerprint"]) == 64
    assert selected["partial"] is False
    assert selected["failed_pages"] == []


def test_scenario_seed_never_enters_direct_records():
    current = service()
    seed = current.register_scenario_seed(
        {
            "geometry": {"type": "Point", "coordinates": [129.4, 37.1]},
            "reference_time": "2026-08-23T00:00:00Z",
            "created_by": "test",
        }
    )
    result = current.search_observations(
        allowed_modes=["CACHED", "SYNTHETIC"], include_scenario_seeds=True
    )
    assert all(record.get("seed_id") != seed["seed_id"] for record in result.data["records"])
    assert result.data["scenario_seeds"][0]["seed_id"] == seed["seed_id"]


def test_live_failure_does_not_silently_select_synthetic():
    result = service().get_field_status(allowed_modes=["LIVE"])
    assert result.status == "BLOCKED"
    assert result.data["selected_field_ref"] is None
    assert result.synthetic_dependency is False
    assert any(item["source_id"] == "khoa_roms_live" for item in result.excluded_sources)


def test_synthetic_field_requires_explicit_mode_and_is_watermarked():
    result = service().get_field_status(allowed_modes=["SYNTHETIC"])
    assert result.status == "READY"
    assert result.synthetic_dependency is True
    assert result.watermark_code == "SYNTHETIC_SCENARIO"
    assert result.data["selected_field_ref"].startswith("synthetic:")


def test_optional_cached_context_does_not_mark_calculation_as_replay():
    current = service()
    synthetic = current.get_field_status(allowed_modes=["SYNTHETIC", "CACHED"])
    assert synthetic.input_mode_set == ["SYNTHETIC"]
    assert synthetic.replay_dependency is False
    assert synthetic.watermark_code == "SYNTHETIC_SCENARIO"
    assert any(item["role"] == "optional_context" for item in synthetic.selected_sources)

    blocked = current.get_field_status(allowed_modes=["CACHED"])
    assert blocked.input_mode_set == []
    assert blocked.effective_mode is None
    assert blocked.replay_dependency is False
    assert blocked.watermark_code is None


def test_p0_transport_and_intersection_are_explicitly_blocked():
    current = service()
    seed = current.register_scenario_seed(
        {
            "geometry": {"type": "Point", "coordinates": [129.4, 37.1]},
            "reference_time": "2026-08-23T00:00:00Z",
            "created_by": "test",
        }
    )
    run = current.run_transport(
        seed_ids=[seed["seed_id"]],
        field_ref="synthetic:SYNTH_DOMAIN_HANUL_v1:p0",
        allowed_modes=["CACHED", "SYNTHETIC"],
    )
    assert run.status == "BLOCKED"
    assert run.error.code == "MODEL_BLOCKED"
    assert run.data["computed_metric"] is None
    forbidden_keys = {
        "probability",
        "arrival_probability",
        "blockage_probability",
        "stop_probability",
        "risk_score",
        "eta",
        "eta_minutes",
    }

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()), set())
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    assert forbidden_keys.isdisjoint(keys(run.model_dump(mode="json")))
    intersection = current.intersect_zone(run_id=run.run_id, zone_ids=["DEMO_GATE_NAGOK_v1"])
    assert intersection.status == "BLOCKED"
    assert intersection.data["members_intersected"] is None
    assert intersection.data["display_string"] is None


def test_non_null_boundary_rule_is_rejected_explicitly():
    current = service()
    seed = current.register_scenario_seed(
        {
            "geometry": {"type": "Point", "coordinates": [129.4, 37.1]},
            "reference_time": "2026-08-23T00:00:00Z",
            "created_by": "test",
        }
    )
    run = current.run_transport(
        seed_ids=[seed["seed_id"]],
        field_ref="synthetic:SYNTH_DOMAIN_HANUL_v1:p0",
        boundary_rule="reflect",
        allowed_modes=["SYNTHETIC"],
    )
    assert run.error.code == "SCHEMA_INVALID"
    assert run.data["boundary_rule"] == "reflect"


def test_unknown_zone_is_rejected_before_run_lookup():
    result = service().intersect_zone(run_id="missing", zone_ids=["UNKNOWN_ZONE"])
    assert result.error.code == "ZONE_NOT_FOUND"


def test_field_status_includes_all_p0_candidates():
    result = service().get_field_status(allowed_modes=["CACHED"])
    source_ids = {item["source_id"] for item in result.data["field_candidates"]}
    assert {
        "khoa_roms_live",
        "khoa_hf_current_regression",
        "khoa_roms_blocked_fixture",
        "cached_field",
        "khoa_tw_recent_hanul",
        "synthetic_field",
    } <= source_ids


def test_blocked_observation_search_keeps_stable_response_shape():
    result = service().search_observations(allowed_modes=["LIVE"])
    assert result.status == "BLOCKED"
    assert result.data["excluded_counts"] == {}


def test_observation_filters_preserve_count_invariant():
    result = service().search_observations(
        allowed_modes=["CACHED"],
        presence="not_detected",
        bbox={"lon_min": 129.0, "lon_max": 130.0, "lat_min": 36.0, "lat_max": 38.0},
    )
    assert result.data["candidates_scanned"] == (
        result.data["returned"] + sum(result.data["excluded_counts"].values())
    )
    assert result.data["excluded_counts"] == {"presence": 1}


@pytest.mark.parametrize(
    ("kwargs", "message_fragment"),
    [
        ({"min_evidence_grade": "HIGH"}, "D0..D5"),
        ({"cursor": "not-an-integer"}, "invalid literal"),
        ({"limit": 0}, "positive"),
        ({"bbox": {"lon_min": 129.0}}, "bbox requires"),
    ],
)
def test_invalid_observation_filter_is_schema_error(kwargs, message_fragment):
    result = service().search_observations(allowed_modes=["CACHED"], **kwargs)
    assert result.status == "BLOCKED"
    assert result.error.code == "SCHEMA_INVALID"
    assert message_fragment in result.error.message


def test_offline_service_never_opens_a_network_socket(monkeypatch):
    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("offline fixture path attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    current = service()
    assert current.search_observations(allowed_modes=["CACHED"]).status == "READY"
    assert current.get_field_status(allowed_modes=["CACHED"]).status == "BLOCKED"


def test_direct_observation_id_is_not_a_registered_scenario_seed():
    run = service().run_transport(
        seed_ids=["OBS-HANUL-HIST-001"], field_ref=None, allowed_modes=["CACHED"]
    )
    assert run.status == "BLOCKED"
    assert run.error.code == "NO_OBSERVATION"
    assert run.error.unavailable_reason == "no_seed"


def test_zones_are_prototype_gates_not_facility_geometry():
    result = service().list_zones()
    assert {zone["zone_id"] for zone in result.data["zones"]} == {
        "DEMO_GATE_ONYANG_v1",
        "DEMO_GATE_DEOKCHEON_v1",
        "DEMO_GATE_NAGOK_v1",
    }
    assert all(zone["facility_geometry"] is None for zone in result.data["zones"])
    assert all(zone["disclaimer_code"] == "NOT_INTAKE_STRUCTURE" for zone in result.data["zones"])


def test_digest_ignores_volatile_ids_and_time():
    first = service().search_observations(allowed_modes=["CACHED"])
    later = create_service(
        Settings(_env_file=None, blob_root=Path(tempfile.mkdtemp(prefix="jellyguard-test-"))),
        clock=lambda: datetime(2026, 8, 23, 1, 0, tzinfo=UTC),
    ).search_observations(allowed_modes=["CACHED"])
    assert first.query_id != later.query_id
    assert first.as_of != later.as_of
    assert first.deterministic_result_digest == later.deterministic_result_digest


def test_digest_changes_when_request_semantics_change():
    current = service()
    cached = current.get_field_status(allowed_modes=["CACHED"])
    synthetic = current.get_field_status(allowed_modes=["SYNTHETIC"])
    assert cached.deterministic_result_digest != synthetic.deterministic_result_digest


def test_all_public_responses_fit_size_limit():
    current = service()
    responses = [
        current.search_observations(allowed_modes=["CACHED"]),
        current.get_field_status(allowed_modes=["LIVE"]),
        current.get_field_status(allowed_modes=["SYNTHETIC"]),
        current.list_zones(),
    ]
    assert all(len(response.model_dump_json().encode()) < 256 * 1024 for response in responses)


def test_domain_does_not_import_transport_adapters():
    root = Path(__file__).resolve().parents[1] / "src/jellyguard/domain"
    assert root.is_dir()
    checked = 0
    for path in root.rglob("*.py"):
        checked += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(name.startswith("jellyguard.adapters") for name in imported), path
        source = path.read_text(encoding="utf-8")
        assert "datetime.now(" not in source
        assert "uuid4(" not in source
        assert "random." not in source
        assert "socket." not in source
    assert checked > 0


def test_adapters_do_not_read_environment_directly():
    root = Path(__file__).resolve().parents[1] / "src/jellyguard/adapters"
    assert root.is_dir()
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "os.environ" not in source
        assert "getenv(" not in source


def test_station_capabilities_are_not_propagated():
    result = service().get_field_status(allowed_modes=["CACHED"])
    by_station = {item["station_code"]: item for item in result.data["point_context"]}
    assert "wind" in by_station["HB_0008"]["capabilities"]
    assert "wind" not in by_station["HB_0007"]["capabilities"]
    assert "wind" not in by_station["HB_0009"]["capabilities"]
    assert {item["crdir_convention"] for item in by_station.values()} == {"UNVERIFIED"}


def test_raw_payload_supports_partial_page_failure_contract():
    payload = RawPayload(
        source_id="fixture",
        request_spec={},
        redacted_endpoint="fixture://redacted",
        content_checksum="a" * 64,
        request_fingerprint="b" * 64,
        source_data_mode="CACHED",
        adapter_version="test",
        license="test",
        rows_received=2,
        rows_expected=4,
        pages_received=1,
        pages_expected=2,
        partial=True,
        failed_pages=[2],
    )
    assert payload.partial is True
    assert payload.failed_pages == [2]


def test_run_and_audit_survive_service_recreation(tmp_path):
    settings = Settings(_env_file=None, blob_root=tmp_path)
    first = create_service(settings)
    seed = first.register_scenario_seed(
        {
            "geometry": {"type": "Point", "coordinates": [129.4, 37.1]},
            "reference_time": "2026-08-23T00:00:00Z",
            "created_by": "test",
        }
    )
    run = first.run_transport(
        seed_ids=[seed["seed_id"]], field_ref=None, allowed_modes=["SYNTHETIC"]
    )
    second = create_service(settings)
    explanation = second.explain_run(run_id=run.run_id)
    assert explanation.status == "READY"
    assert (tmp_path / "runs.jsonl").is_file()
    assert (tmp_path / "provenance.jsonl").is_file()
    assert (tmp_path / "audit.jsonl").is_file()
