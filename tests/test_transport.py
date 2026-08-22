from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from jellyguard.composition import create_service
from jellyguard.config.settings import Settings
from jellyguard.domain.transport import DomainGrid, run_synthetic_transport

FIXED_NOW = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)


def service():
    counter = 0

    def new_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-TRANSPORT-{counter:04d}"

    return create_service(
        Settings(_env_file=None, blob_root=Path(tempfile.mkdtemp(prefix="jellyguard-p1-"))),
        clock=lambda: FIXED_NOW,
        new_id=new_id,
    )


def field_ref(profile: str) -> str:
    return f"synthetic:SYNTH_DOMAIN_HANUL_v1.{profile}:2026-08-23T00:00:00Z:2026-08-23T00:00:00Z"


def register_seed(current, coordinates=(129.46, 37.1)):
    return current.register_scenario_seed(
        {
            "geometry": {"type": "Point", "coordinates": list(coordinates)},
            "reference_time": "2026-08-23T00:00:00Z",
            "created_by": "test",
        }
    )


def run_profile(current, profile: str, horizons=(3, 6, 12)):
    seed = register_seed(current)
    return current.run_transport(
        seed_ids=[seed["seed_id"]],
        field_ref=field_ref(profile),
        horizons_h=list(horizons),
        scenario_id=profile,
        gate_mapping="DEMO_GATE",
        boundary_rule=None,
        allowed_modes=["SYNTHETIC"],
    )


@pytest.mark.parametrize("profile", ["B0_hold", "B2_current_only", "B3"])
def test_member_conservation_for_every_profile_and_horizon(profile):
    run = run_profile(service(), profile)
    assert run.status == "READY"
    for summary in run.data["computed_metric"]["horizon_summary"].values():
        assert summary["released"] == summary["valid"] + sum(summary["terminated_by"].values())


@pytest.mark.parametrize("profile", ["B0_hold", "B2_current_only"])
def test_non_spread_profiles_do_not_use_rng(monkeypatch, profile):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("B0 must not construct or draw from an RNG")

    monkeypatch.setattr(np.random, "Generator", forbidden)
    current = service()
    run = run_profile(current, profile)
    assert run.status == "READY"
    if profile != "B0_hold":
        return
    artifact_id = run.data["artifact_refs"][0].rsplit("/", 1)[-1]
    artifact = current.artifact_store.get(artifact_id)
    assert all(
        member["trajectory"][0] == member["trajectory"][-1] for member in artifact["members"]
    )


def test_b2_is_deterministic_across_distinct_services():
    first = service()
    second = service()
    first_run = run_profile(first, "B2_current_only")
    second_run = run_profile(second, "B2_current_only")
    assert first_run.run_id == second_run.run_id
    assert first_run.deterministic_result_digest == second_run.deterministic_result_digest
    assert first_run.data["computed_metric"] == second_run.data["computed_metric"]


def test_b3_member_rng_stream_is_independent_of_other_member_termination():
    seed = {
        "seed_id": "SEED-RNG-INDEPENDENCE",
        "geometry": {"type": "Point", "coordinates": [129.46, 37.1]},
    }
    wide = DomainGrid(
        domain_id="wide",
        lon_min=129.40,
        lon_max=129.60,
        lat_min=37.00,
        lat_max=37.20,
        spacing_deg=0.01,
    )
    narrow = DomainGrid(
        domain_id="narrow",
        lon_min=129.455,
        lon_max=129.60,
        lat_min=37.00,
        lat_max=37.20,
        spacing_deg=0.01,
    )
    _, wide_artifact = run_synthetic_transport(
        seeds=[seed], grid=wide, profile_id="B3", horizons_h=[1], run_seed=42
    )
    _, narrow_artifact = run_synthetic_transport(
        seeds=[seed], grid=narrow, profile_id="B3", horizons_h=[1], run_seed=42
    )
    assert any(
        member["terminated_reason"] == "out_of_domain" for member in narrow_artifact["members"][:-1]
    )
    assert (
        wide_artifact["members"][-1]["trajectory"] == narrow_artifact["members"][-1]["trajectory"]
    )


def test_run_exposes_reproducibility_manifest():
    current = service()
    run = run_profile(current, "B3")
    expected = {
        "run_seed": run.data["reproducibility"]["run_seed"],
        "rng_algorithm": "PCG64",
        "quantization": {"coordinate_deg": 1e-7, "physical": 1e-6},
        "float_policy": "float64_rk4_fixed_no_parallel_reduce_sorted_index",
        "reproducibility_class": "quantized_cross_env",
    }
    assert run.data["reproducibility"] == expected
    assert run.data["computed_metric"]["reproducibility"] == expected
    artifact_id = run.data["artifact_refs"][0].rsplit("/", 1)[-1]
    assert current.artifact_store.get(artifact_id)["reproducibility"] == expected


def test_repeated_request_has_new_run_id_but_same_digest():
    current = service()
    seed = register_seed(current)
    request = {
        "seed_ids": [seed["seed_id"]],
        "field_ref": field_ref("B2_current_only"),
        "horizons_h": [3, 6, 12],
        "scenario_id": "B2_current_only",
        "gate_mapping": "DEMO_GATE",
        "boundary_rule": None,
        "allowed_modes": ["SYNTHETIC"],
    }
    first = current.run_transport(**request)
    second = current.run_transport(**request)
    assert first.run_id != second.run_id
    assert first.deterministic_result_digest == second.deterministic_result_digest


def test_gate_sensitivity_is_monotonic_and_never_percentized():
    current = service()
    run = run_profile(current, "B2_current_only")
    result = current.intersect_zone(
        run_id=run.run_id,
        zone_ids=[zone["zone_id"] for zone in current.demo_zones],
        horizons_h=[3, 6, 12],
    )
    assert result.status == "READY"
    for zone in result.data["zones"]:
        for horizon_index in range(3):
            core = zone["sensitivity"]["core"]["by_horizon"][horizon_index]
            edge4 = zone["sensitivity"]["edge4"]["by_horizon"][horizon_index]
            edge8 = zone["sensitivity"]["edge8"]["by_horizon"][horizon_index]
            assert core["members_intersected"] <= edge4["members_intersected"]
            assert edge4["members_intersected"] <= edge8["members_intersected"]
            assert core["display_string"].endswith(f"of {core['members_total']}")
    serialized = result.model_dump(mode="json")
    assert all(term not in str(serialized).lower() for term in ("probability", "percent", "eta"))
    assert result.watermark_code == "SYNTHETIC_SCENARIO"
    assert result.data["disclaimer_code"] == "NOT_INTAKE_STRUCTURE"
    assert len(result.warnings) >= 3


def test_run_keeps_all_three_required_disclaimers_and_trajectory_is_blob_only():
    run = run_profile(service(), "B2_current_only")
    assert run.watermark_code == "SYNTHETIC_SCENARIO"
    assert run.data["disclaimer_code"] == "NOT_INTAKE_STRUCTURE"
    assert len(run.warnings) >= 3
    assert [item["source_id"] for item in run.selected_sources] == [
        "scenario_seed_synthetic",
        "synthetic_field",
    ]
    assert all(len(item["content_checksum"]) == 64 for item in run.selected_sources)
    assert "trajectory" not in run.model_dump_json()
    assert len(run.model_dump_json().encode()) < 256 * 1024


def test_two_seeds_release_fifty_ordered_members():
    current = service()
    second = register_seed(current, coordinates=(129.45, 37.09))
    run = current.run_transport(
        seed_ids=[second["seed_id"], "SEED-HANUL-DEMO-001"],
        field_ref=field_ref("B0_hold"),
        allowed_modes=["SYNTHETIC"],
    )
    assert run.status == "READY"
    assert run.data["computed_metric"]["released"] == 50
    artifact_id = run.data["artifact_refs"][0].rsplit("/", 1)[-1]
    members = current.artifact_store.get(artifact_id)["members"]
    assert [member["member_index"] for member in members] == list(range(50))
    assert [member["seed_id"] for member in members[:25]] == ["SEED-HANUL-DEMO-001"] * 25


def test_zone_versions_are_unique_per_zone_and_neighbor_mode():
    current = service()
    versions = [
        version for zone in current.demo_zones for version in zone["zone_version_by_mode"].values()
    ]
    assert len(versions) == 9
    assert len(set(versions)) == 9


def test_zone_version_change_is_reported_without_recalculation():
    current = service()
    run = run_profile(current, "B2_current_only")
    current.demo_zones[0]["zone_version_by_mode"]["core"] = "changed-version"
    result = current.intersect_zone(
        run_id=run.run_id,
        zone_ids=[current.demo_zones[0]["zone_id"]],
        horizons_h=[3, 6, 12],
    )
    assert result.status == "READY"
    assert any("ZONE_VERSION_MISMATCH" in warning for warning in result.warnings)
    assert "changed-version" in result.data["current_zone_versions"]
    assert "changed-version" not in result.data["recorded_zone_versions"]
    assert result.data["zones"][0]["zone_version_by_mode"]["core"] != "changed-version"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"horizons_h": []}, "SCHEMA_INVALID"),
        ({"horizons_h": [25]}, "SCHEMA_INVALID"),
        ({"gate_mapping": "INTAKE"}, "GATE_MAPPING_BLOCKED"),
        ({"allowed_modes": ["CACHED"]}, "MODEL_BLOCKED"),
        ({"field_ref": "synthetic:OTHER.B2_current_only:x:y"}, "NO_COMPATIBLE_SOURCE"),
        ({"field_ref": "synthetic:SYNTH_DOMAIN_HANUL_v1.UNKNOWN:x:y"}, "SCHEMA_INVALID"),
        ({"field_ref": "cached:khoa_tw_recent_hanul:HB_0008"}, "DIRECTION_UNVERIFIED"),
    ],
)
def test_transport_rejects_unapproved_inputs(changes, code):
    current = service()
    seed = register_seed(current)
    request = {
        "seed_ids": [seed["seed_id"]],
        "field_ref": field_ref("B2_current_only"),
        "horizons_h": [3, 6, 12],
        "scenario_id": "B2_current_only",
        "gate_mapping": "DEMO_GATE",
        "boundary_rule": None,
        "allowed_modes": ["SYNTHETIC"],
    }
    request.update(changes)
    run = current.run_transport(**request)
    assert run.status == "BLOCKED"
    assert run.error.code == code


def test_transport_rejects_non_point_and_outside_seed():
    current = service()
    polygon = current.register_scenario_seed(
        {
            "geometry": {"type": "Polygon", "coordinates": []},
            "reference_time": "2026-08-23T00:00:00Z",
            "created_by": "test",
        }
    )
    invalid = current.run_transport(
        seed_ids=[polygon["seed_id"]],
        field_ref=field_ref("B0_hold"),
        allowed_modes=["SYNTHETIC"],
    )
    assert invalid.error.code == "SCHEMA_INVALID"

    outside = register_seed(current, coordinates=(130.0, 38.0))
    blocked = current.run_transport(
        seed_ids=[outside["seed_id"]],
        field_ref=field_ref("B0_hold"),
        allowed_modes=["SYNTHETIC"],
    )
    assert blocked.error.code == "MODEL_BLOCKED"
    assert blocked.error.unavailable_reason == "outside_coverage"


def test_transport_rejects_non_finite_coordinates_and_duplicate_seed_ids():
    current = service()
    invalid = register_seed(current, coordinates=(float("nan"), 37.1))
    malformed = current.run_transport(
        seed_ids=[invalid["seed_id"]],
        field_ref=field_ref("B0_hold"),
        allowed_modes=["SYNTHETIC"],
    )
    assert malformed.error.code == "SCHEMA_INVALID"

    duplicate = current.run_transport(
        seed_ids=["SEED-HANUL-DEMO-001", "SEED-HANUL-DEMO-001"],
        field_ref=field_ref("B0_hold"),
        allowed_modes=["SYNTHETIC"],
    )
    assert duplicate.error.code == "SCHEMA_INVALID"


def test_blocked_run_never_produces_intersection_members():
    current = service()
    seed = register_seed(current)
    blocked = current.run_transport(
        seed_ids=[seed["seed_id"]],
        field_ref=field_ref("B0_hold"),
        allowed_modes=["CACHED"],
    )
    result = current.intersect_zone(
        run_id=blocked.run_id,
        zone_ids=["DEMO_GATE_NAGOK_v1"],
    )
    assert result.status == "BLOCKED"
    assert result.error.code == "MODEL_BLOCKED"
    assert result.data["members_intersected"] is None


def test_ready_run_artifact_survives_service_restart(tmp_path):
    settings = Settings(_env_file=None, blob_root=tmp_path)
    first = create_service(settings)
    run = first.run_transport(
        seed_ids=["SEED-HANUL-DEMO-001"],
        field_ref=field_ref("B2_current_only"),
        allowed_modes=["SYNTHETIC"],
    )
    assert run.status == "READY"
    second = create_service(settings)
    intersection = second.intersect_zone(
        run_id=run.run_id,
        zone_ids=["DEMO_GATE_NAGOK_v1"],
        horizons_h=[3, 6, 12],
    )
    assert intersection.status == "READY"
    assert (tmp_path / "artifacts.jsonl").is_file()


def _measured_rows(bearing_degrees=0.0, speed=0.2):
    """A uniform field covering a small lat/lon box for two hours."""
    rows = []
    for lat in (37.05, 37.08, 37.11):
        for lon in (129.40, 129.44, 129.48):
            for hour in range(3):
                rows.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "valid_at": f"2026-08-22 {hour:02d}:00:00",
                        "current_direction": bearing_degrees,
                        "current_speed": speed,
                        "water_temperature": 20.0,
                    }
                )
    return rows


def test_measured_field_refuses_to_fill_gaps_between_grid_points():
    from jellyguard.domain.transport import MeasuredField

    # Drop one corner cell so some squares stay complete and one is holed.
    rows = [row for row in _measured_rows() if not (row["lat"] == 37.11 and row["lon"] == 129.48)]
    field = MeasuredField.from_rows(rows, field_id="test", convention="TOWARD")

    # A position whose surrounding square is complete still samples.
    assert field.sample(129.42, 37.06, 0.0) is not None
    # The square missing one corner is refused rather than filled from a neighbour.
    assert field.sample(129.45, 37.09, 0.0) is None
    # Outside the field footprint there is nothing to interpolate.
    assert field.sample(129.90, 37.06, 0.0) is None
    # Beyond the last forecast hour the field cannot answer either.
    assert field.sample(129.42, 37.06, 10 * 3600) is None


def test_measured_field_flips_components_with_the_convention():
    from jellyguard.domain.transport import MeasuredField

    north = MeasuredField.from_rows(_measured_rows(0.0), field_id="t", convention="TOWARD")
    same_rows_from = MeasuredField.from_rows(_measured_rows(0.0), field_id="t", convention="FROM")
    u_toward, v_toward = north.sample(129.42, 37.06, 0.0)
    u_from, v_from = same_rows_from.sample(129.42, 37.06, 0.0)
    assert v_toward > 0 and v_from < 0
    assert u_toward == pytest.approx(-u_from)


def test_measured_field_requires_a_settled_convention():
    from jellyguard.domain.transport import MeasuredField

    with pytest.raises(ValueError, match="convention"):
        MeasuredField.from_rows(_measured_rows(), field_id="t", convention="INCONCLUSIVE")


def test_measured_transport_reports_domain_exit_instead_of_a_clipped_envelope():
    from jellyguard.domain.transport import DomainGrid, MeasuredField, run_measured_transport

    grid = DomainGrid(
        domain_id="TEST_DOMAIN",
        lon_min=129.40,
        lon_max=129.48,
        lat_min=37.05,
        lat_max=37.11,
        spacing_deg=0.01,
    )
    field = MeasuredField.from_rows(_measured_rows(0.0, 0.5), field_id="t", convention="TOWARD")
    seeds = [{"seed_id": "S1", "geometry": {"type": "Point", "coordinates": [129.44, 37.10]}}]

    public, _ = run_measured_transport(
        seeds=seeds, grid=grid, field=field, horizons_h=[1, 2], run_seed=1
    )

    # A fast northward flow pushes the cloud past the northern edge within the window.
    assert public["domain_insufficient_horizons"]
    assert public["domain_exit_fraction"]["2"] > public["domain_exit_tolerance"]
    assert public["field_source"]["crdir_convention"] == "TOWARD"
    assert public["field_constants"] is None
