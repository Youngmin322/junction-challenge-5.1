"""The dashboard's current-vector overlay must never outrun what the check settled.

Drawing an arrow is a direction claim. These tests pin the three outcomes apart: a settled
convention produces arrows plus the check-based badge, an unsettled one produces no arrows
and says why, and a missing field says it is missing instead of looking like calm water.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jellyguard.composition import create_service
from jellyguard.config.settings import Settings
from jellyguard.contracts import DataMode
from jellyguard.domain.source_state import SourceResolution, SourceState
from jellyguard.domain.transport import (
    DASHBOARD_VECTOR_LIMIT,
    MeasuredField,
    downsample_field_vectors,
)

FIXED_NOW = datetime(2026, 8, 23, tzinfo=UTC)

# Inside the synthetic domain bbox, so the projected arrows land on the plot.
LATS = [37.00 + 0.02 * index for index in range(6)]
LONS = [129.38 + 0.02 * index for index in range(5)]


def service():
    counter = 0

    def new_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-VECTOR-{counter:04d}"

    return create_service(
        Settings(_env_file=None, blob_root=Path(tempfile.mkdtemp(prefix="jellyguard-vector-"))),
        clock=lambda: FIXED_NOW,
        new_id=new_id,
    )


def roms_rows(*, bearing: float = 90.0, speed: float = 0.4) -> list[dict]:
    rows = []
    for hour in range(3):
        for lat in LATS:
            for lon in LONS:
                rows.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "valid_at": f"2026-08-23 {hour:02d}:00:00",
                        "current_direction": bearing,
                        "current_speed": speed,
                        "water_temperature": 20.0,
                        "crdir_convention": "UNVERIFIED",
                    }
                )
    return rows


def grid_summary(verdict: str) -> dict:
    return {
        "is_area_field": True,
        "cell_count": len(LATS) * len(LONS),
        "valid_from_local": "2026-08-23 00:00:00",
        "crdir_convention": "UNVERIFIED",
        "convention_check": {
            "verdict": verdict,
            "method": "temperature_advection_sign_test",
            "correlation_toward": 0.31 if verdict != "INCONCLUSIVE" else 0.02,
            "sample_size": 1240,
            "provider_documented": False,
        },
    }


def install_roms(current, *, verdict: str, rows: list[dict] | None = None) -> None:
    """Answer only for the ROMS source so every other source keeps its real resolution."""
    original = current.source_resolver.resolve

    def resolve(source_id: str, allowed_modes: list[DataMode]) -> SourceResolution:
        if source_id != "khoa_roms_live":
            return original(source_id, allowed_modes)
        return SourceResolution(
            source_id=source_id,
            source_class="field",
            optional=True,
            state=SourceState.LIVE_OK,
            data_mode=DataMode.LIVE.value,
            payload=roms_rows() if rows is None else rows,
            manifest={"source_id": source_id, "grid_summary": grid_summary(verdict)},
        )

    current.source_resolver.resolve = resolve


def vectors(result) -> dict:
    return result.data["current_vectors"]


def test_settled_convention_publishes_downsampled_vectors_with_check_based_basis():
    current = service()
    install_roms(current, verdict="TOWARD")
    facts = vectors(current.dashboard_bootstrap())

    assert facts["state"] == "AVAILABLE"
    assert facts["convention"] == "TOWARD"
    assert facts["convention_check"]["provider_documented"] is False
    assert facts["convention_check"]["sample_size"] == 1240
    assert 0 < facts["vector_count"] <= DASHBOARD_VECTOR_LIMIT
    assert facts["vector_count"] == len(facts["vectors"])
    assert facts["vector_count"] < facts["field_cell_count"]
    sample = facts["vectors"][0]
    assert set(sample) == {"lon", "lat", "u_ms", "v_ms", "speed_ms", "bearing_deg_toward"}
    # A 090 bearing under TOWARD is water moving east: positive u, no northward part.
    assert sample["u_ms"] > 0
    assert sample["v_ms"] == pytest.approx(0.0, abs=1e-9)


def test_from_convention_flips_the_components_rather_than_reusing_the_raw_bearing():
    current = service()
    install_roms(current, verdict="FROM")
    facts = vectors(current.dashboard_bootstrap())

    assert facts["state"] == "AVAILABLE"
    assert facts["convention"] == "FROM"
    # 090 under FROM means the water comes from the east, so it flows west.
    assert facts["vectors"][0]["u_ms"] < 0


def test_inconclusive_convention_withholds_every_vector_and_says_why():
    current = service()
    install_roms(current, verdict="INCONCLUSIVE")
    result = current.dashboard_bootstrap()
    facts = vectors(result)

    assert facts["state"] == "WITHHELD_UNVERIFIED_CONVENTION"
    assert facts["vectors"] == []
    assert facts["vector_count"] == 0
    assert facts["convention"] is None
    assert facts["reason_code"] == "DIRECTION_UNVERIFIED"
    assert "표시하지 않습니다" in facts["public_message"]
    assert facts["public_message"] in result.warnings


def test_absent_field_reports_the_absence_instead_of_an_empty_vector_list():
    result = service().dashboard_bootstrap()
    facts = vectors(result)

    assert facts["state"] == "NO_FIELD"
    assert facts["vectors"] == []
    assert facts["convention"] is None
    assert facts["reason_code"] == "LIVE_NOT_ENABLED"
    assert facts["public_message"] in result.warnings


def test_unreadable_field_rows_are_reported_as_a_schema_problem():
    current = service()
    install_roms(current, verdict="TOWARD", rows=[{"lat": 37.0, "lon": 129.4}])
    facts = vectors(current.dashboard_bootstrap())

    assert facts["state"] == "NO_FIELD"
    assert facts["reason_code"] == "SCHEMA_INVALID"


def test_downsampling_spreads_over_the_grid_instead_of_truncating_one_corner():
    field = MeasuredField.from_rows(roms_rows(), field_id="test", convention="TOWARD")
    picked = downsample_field_vectors(field, limit=DASHBOARD_VECTOR_LIMIT)

    assert len(picked) <= DASHBOARD_VECTOR_LIMIT
    assert min(item["lat"] for item in picked) == pytest.approx(min(LATS))
    assert max(item["lat"] for item in picked) > min(LATS)
    assert max(item["lon"] for item in picked) > min(LONS)
    # One timestep only: the overlay is a snapshot, not the whole forecast window.
    assert len({(item["lat"], item["lon"]) for item in picked}) == len(picked)


def test_bootstrap_vector_payload_stays_small_enough_to_be_a_projection():
    current = service()
    install_roms(current, verdict="TOWARD")
    payload = current.dashboard_bootstrap().model_dump_json().encode()

    assert len(payload) < 256 * 1024

