"""Contract tests for the risk-zone connectivity engine behind run_transport."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

import pytest

from jellyguard.composition import create_service
from jellyguard.config.settings import Settings
from jellyguard.contracts import CalculationStatus, ErrorCode
from jellyguard.domain.connectivity import ENGINE_ID as RISK_ZONE_ENGINE

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="risk-zone engine needs a Node runtime"
)


def build_service(tmp_path, **overrides):
    settings = Settings(_env_file=None, blob_root=tmp_path, **overrides)
    return create_service(settings, clock=lambda: datetime(2026, 8, 23, tzinfo=UTC))


def run_engine(service, engine=RISK_ZONE_ENGINE, horizons=(3, 6, 12)):
    field_ref = service.get_field_status(allowed_modes=["SYNTHETIC"]).data["selected_field_ref"]
    return service.run_transport(
        seed_ids=["SEED-HANUL-DEMO-001"],
        field_ref=field_ref,
        horizons_h=list(horizons),
        allowed_modes=["SYNTHETIC"],
        engine=engine,
    )


def test_engine_returns_ready_run_with_gate_connectivity(tmp_path):
    run = run_engine(build_service(tmp_path))

    assert run.status == CalculationStatus.READY.value
    assert run.data["engine_version"] == RISK_ZONE_ENGINE
    metric = run.data["computed_metric"]
    assert metric["engine"] == RISK_ZONE_ENGINE
    assert metric["released"] == 25
    assert set(metric["gate_connectivity"]) == {
        "DEMO_GATE_ONYANG_v1",
        "DEMO_GATE_DEOKCHEON_v1",
        "DEMO_GATE_NAGOK_v1",
    }
    for zone in metric["gate_connectivity"].values():
        for horizon in zone["by_horizon"]:
            assert horizon["connected_members"] <= horizon["members_total"]
            assert horizon["display_string"] == (
                f"{horizon['connected_members']} of {horizon['members_total']}"
            )


def test_gate_is_laid_perpendicular_to_the_synthetic_field(tmp_path):
    geometry = run_engine(build_service(tmp_path)).data["computed_metric"]["gate_geometry"]

    # B2_current_only travels at bearing 288.43 degrees, so an intercepting
    # gate sits 90 degrees off it.
    assert geometry["bearing_basis"] == "perpendicular_to_synthetic_field"
    assert geometry["bearing_deg"] == pytest.approx(18.43, abs=0.01)


def test_engine_declares_its_synthetic_inputs(tmp_path):
    run = run_engine(build_service(tmp_path))
    metric = run.data["computed_metric"]

    assert metric["physical_realism"] == "none"
    assert metric["coastline_basis"] == "synthetic_flat_bathymetry"
    assert "blockage probability" in metric["disclaimer"]
    source_ids = {source["source_id"] for source in run.selected_sources}
    assert "synthetic_bathymetry_flat" in source_ids
    assert run.synthetic_dependency is True
    assert run.watermark_code == "SYNTHETIC_SCENARIO"


def test_result_never_exposes_an_eta(tmp_path):
    """The product contract allows a horizon bracket, never a predicted ETA."""

    run = run_engine(build_service(tmp_path))

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()), set())
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    assert {"eta", "eta_minutes", "probability"}.isdisjoint(keys(run.model_dump(mode="json")))
    for zone in run.data["computed_metric"]["gate_connectivity"].values():
        window = zone["first_crossing_window"]
        assert window is None or window["basis"] == "requested_horizon_bracket"


def test_engine_run_feeds_intersect_zone_unchanged(tmp_path):
    service = build_service(tmp_path)
    run = run_engine(service)

    result = service.intersect_zone(
        run_id=run.run_id, zone_ids=["DEMO_GATE_DEOKCHEON_v1"], horizons_h=[3, 6, 12]
    )

    assert result.status == CalculationStatus.READY.value
    assert result.data["engine"] == RISK_ZONE_ENGINE
    # Both readings are returned because they answer different questions: cell
    # occupancy versus crossing a gate line.
    assert result.data["gate_connectivity"] is not None
    sensitivity = result.data["zones"][0]["sensitivity"]
    assert set(sensitivity) == {"core", "edge4", "edge8"}
    for mode in sensitivity.values():
        for horizon in mode["by_horizon"]:
            assert horizon["members_intersected"] <= horizon["members_total"]


def test_same_request_reproduces_the_same_digest(tmp_path):
    first = run_engine(build_service(tmp_path))
    second = run_engine(build_service(tmp_path / "second"))

    assert first.data["computed_metric"] == second.data["computed_metric"]
    assert (
        first.data["computed_metric"]["reproducibility"]["reproducibility_class"]
        == "exact_same_engine_bundle"
    )


def test_engines_are_reported_separately_and_do_not_share_numbers(tmp_path):
    service = build_service(tmp_path)

    synthetic = run_engine(service, engine="synthetic-rk4-v1")
    connectivity = run_engine(service, engine=RISK_ZONE_ENGINE)

    assert synthetic.data["engine_version"] == "synthetic-rk4-v1"
    assert "gate_connectivity" not in synthetic.data["computed_metric"]
    assert connectivity.data["artifact_refs"] != synthetic.data["artifact_refs"]
    assert connectivity.deterministic_result_digest != synthetic.deterministic_result_digest


def test_unknown_engine_is_rejected(tmp_path):
    run = run_engine(build_service(tmp_path), engine="made-up-engine")

    assert run.status == CalculationStatus.BLOCKED.value
    assert run.error.code == ErrorCode.SCHEMA_INVALID.value
    assert run.data["computed_metric"] is None


def test_disabled_engine_blocks_instead_of_falling_back(tmp_path):
    service = build_service(tmp_path, risk_zone_engine_enabled=False)

    run = run_engine(service)

    assert run.status == CalculationStatus.BLOCKED.value
    assert run.error.code == ErrorCode.ENGINE_UNAVAILABLE.value
    # A silent swap to the synthetic engine would misreport which model ran.
    assert run.data["computed_metric"] is None
    assert run.data["engine"] == RISK_ZONE_ENGINE


def test_missing_bundle_blocks_with_a_recovery_instruction(tmp_path):
    service = build_service(tmp_path, risk_zone_bridge=tmp_path / "absent.mjs")

    run = run_engine(service)

    assert run.error.code == ErrorCode.ENGINE_UNAVAILABLE.value
    assert run.error.required
