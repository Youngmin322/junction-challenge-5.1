"""Adapter that runs the risk-zone TypeScript engine as a transport engine.

The engine is published as a dependency-free ESM bundle and invoked through a
short-lived Node process. Only the engine's own physics stays in TypeScript;
grid-cell bookkeeping is done here with the same :class:`DomainGrid` the
synthetic engine uses, so the two engines cannot disagree about which cell a
position belongs to.

A failure never falls back to the synthetic engine. The caller is expected to
turn :class:`RiskZoneEngineError` into a BLOCKED result with an explicit
reason, because a silent engine swap would misrepresent the numbers.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jellyguard.config.settings import Settings

from .transport import DomainGrid

ENGINE_ID = "risk-zone-connectivity-v1"
BRIDGE_REQUEST_VERSION = "risk-zone-bridge-v1"

# Demo parameters for the synthetic Hanul profile. They are inputs, not
# measurements, and every one of them is echoed back in the result.
ENSEMBLE_SIZE_PER_SEED = 25
POSITION_UNCERTAINTY_M = 500.0
PARTICLE_DEPTH_M = 1.0
SEED_CONFIDENCE = 0.8
SEED_SPECIES = "jellyfish"
FLAT_DEPTH_M = 30.0
MINIMUM_WATER_DEPTH_M = 2.0
BATHYMETRY_LOOKUP_RADIUS_M = 800.0
GATE_WIDTH_M = 4000.0
GATE_MIN_DEPTH_M = 0.0
GATE_MAX_DEPTH_M = 5.0
TIME_STEP_MINUTES = 15
SNAPSHOT_INTERVAL_MINUTES = 60
REGION_CELL_SIZE_M = 1000.0

# TS particle status -> the terminated_reason vocabulary already used by the
# synthetic engine, extended with the two reasons only this engine can produce.
_STATUS_TO_REASON = {
    "active": None,
    "gate-reached": None,
    "blocked-land": "blocked_land",
    "blocked-shallow-water": "blocked_shallow_water",
    "outside-navigability-coverage": "out_of_domain",
    "outside-flow-coverage": "forecast_unavailable",
}
_TERMINATION_REASONS = (
    "out_of_domain",
    "forecast_unavailable",
    "field_missing",
    "blocked_land",
    "blocked_shallow_water",
)


class RiskZoneEngineError(RuntimeError):
    """Raised when the engine cannot be run or refused the request."""

    def __init__(self, code: str, message: str, required: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.required = required or []


# src/jellyguard/domain/connectivity.py -> repository root
_REPO_ROOT = Path(__file__).resolve().parents[3]


def bridge_path(settings: Settings) -> Path:
    """Resolve the bundle against the working directory, then the repo root.

    The second attempt lets ``jellyguard`` be started from any directory
    without the operator having to set an absolute path.
    """

    configured = Path(settings.risk_zone_bridge)
    if configured.is_absolute():
        return configured
    from_cwd = (Path.cwd() / configured).resolve()
    if from_cwd.is_file():
        return from_cwd
    return (_REPO_ROOT / configured).resolve()


def bundle_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


def ensure_available(settings: Settings) -> Path:
    """Check the engine can run before any request is built."""

    if not settings.risk_zone_engine_enabled:
        raise RiskZoneEngineError(
            "ENGINE_UNAVAILABLE",
            "risk-zone 엔진이 설정에서 비활성화되어 있습니다.",
            ["JELLYGUARD_RISK_ZONE_ENGINE_ENABLED=true"],
        )
    if shutil.which(settings.risk_zone_node_bin) is None:
        raise RiskZoneEngineError(
            "ENGINE_UNAVAILABLE",
            f"Node 실행파일을 찾을 수 없습니다: {settings.risk_zone_node_bin}",
            ["Node.js 22 이상 설치", "JELLYGUARD_RISK_ZONE_NODE 설정"],
        )
    path = bridge_path(settings)
    if not path.is_file():
        raise RiskZoneEngineError(
            "ENGINE_UNAVAILABLE",
            f"risk-zone 번들이 없습니다: {path}",
            ["engines/risk-zone에서 npm run build:bridge 실행"],
        )
    return path


def build_request(
    *,
    seeds: list[dict[str, Any]],
    grid: DomainGrid,
    profile_id: str,
    field_constants: dict[str, Any],
    horizons_h: list[int],
    zones: list[dict[str, Any]],
    run_seed: int,
    field_ref: str,
) -> dict[str, Any]:
    issued_at, valid_at = field_ref.split(":")[-2:]
    return {
        "request_version": BRIDGE_REQUEST_VERSION,
        "seeds": [
            {
                "seed_id": seed["seed_id"],
                "lon": seed["geometry"]["coordinates"][0],
                "lat": seed["geometry"]["coordinates"][1],
                "reference_time": seed["reference_time"],
            }
            for seed in sorted(seeds, key=lambda item: item["seed_id"])
        ],
        "field": {
            "profile_id": profile_id,
            "u_ms": field_constants["u_ms"],
            "v_ms": field_constants["v_ms"],
            "issued_at": issued_at,
            "valid_at": valid_at,
        },
        "horizons_h": sorted(horizons_h),
        "domain": {
            "domain_id": grid.domain_id,
            "lon_min": grid.lon_min,
            "lon_max": grid.lon_max,
            "lat_min": grid.lat_min,
            "lat_max": grid.lat_max,
            "spacing_deg": grid.spacing_deg,
        },
        "zones": [
            {"zone_id": zone["zone_id"], "lon": zone["lon"], "lat": zone["lat"]} for zone in zones
        ],
        "ensemble": {
            "size": ENSEMBLE_SIZE_PER_SEED,
            "position_uncertainty_m": POSITION_UNCERTAINTY_M,
            "depth_m": PARTICLE_DEPTH_M,
            "confidence": SEED_CONFIDENCE,
            "species": SEED_SPECIES,
        },
        "navigability": {
            "mode": "synthetic_flat",
            "flat_depth_m": FLAT_DEPTH_M,
            "minimum_water_depth_m": MINIMUM_WATER_DEPTH_M,
            "lookup_radius_m": BATHYMETRY_LOOKUP_RADIUS_M,
            "land_polygons": [],
        },
        # bearing_deg stays null so the engine lays each gate perpendicular to
        # the field vector instead of an arbitrary compass direction.
        "gate": {
            "width_m": GATE_WIDTH_M,
            "bearing_deg": None,
            "min_depth_m": GATE_MIN_DEPTH_M,
            "max_depth_m": GATE_MAX_DEPTH_M,
        },
        "config": {
            "time_step_minutes": TIME_STEP_MINUTES,
            "snapshot_interval_minutes": SNAPSHOT_INTERVAL_MINUTES,
            "region_cell_size_m": REGION_CELL_SIZE_M,
            "random_seed": run_seed % (2**32),
        },
    }


def invoke_bridge(settings: Settings, request: dict[str, Any]) -> dict[str, Any]:
    path = ensure_available(settings)
    try:
        completed = subprocess.run(
            [settings.risk_zone_node_bin, str(path)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=settings.risk_zone_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RiskZoneEngineError(
            "ENGINE_FAILED",
            f"risk-zone 엔진이 {settings.risk_zone_timeout_s}초 안에 끝나지 않았습니다.",
        ) from exc
    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RiskZoneEngineError(
            "ENGINE_FAILED", "risk-zone 엔진이 JSON이 아닌 출력을 반환했습니다."
        ) from exc
    if not envelope.get("ok"):
        raise RiskZoneEngineError(
            "ENGINE_FAILED", f"risk-zone 엔진 거절: {envelope.get('error', 'unknown')}"
        )
    return envelope["result"]


def _members_from_particles(
    result: dict[str, Any], grid: DomainGrid, total_steps: int
) -> list[dict[str, Any]]:
    step_minutes = result["time_step_minutes"]
    members: list[dict[str, Any]] = []
    for particle in result["particles"]:
        coordinates = particle["coordinates"]
        reason = _STATUS_TO_REASON.get(particle["status"], "field_missing")
        visited: dict[str, int] = {}
        last_index = len(coordinates) - 1
        for index, (lon, lat) in enumerate(coordinates):
            cell_id = grid.cell_id(lon, lat)
            if cell_id is None:
                # Leaving the synthetic domain ends the track here, matching the
                # synthetic engine rather than recording cells we cannot name.
                reason = reason or "out_of_domain"
                last_index = index - 1
                break
            visited.setdefault(cell_id, index * step_minutes)
        last_index = max(last_index, 0)
        survived = reason is None and last_index >= total_steps
        lon, lat = coordinates[last_index]
        members.append(
            {
                "member_index": len(members),
                "seed_id": particle["seed_id"],
                "lon": lon,
                "lat": lat,
                "terminated_reason": None if survived else (reason or "out_of_domain"),
                "terminated_at_minutes": None if survived else last_index * step_minutes,
                "visited_cells": visited,
                "trajectory": [list(position) for position in coordinates[: last_index + 1]],
                "status": particle["status"],
                "last_step_index": last_index,
            }
        )
    return members


def run_risk_zone_transport(
    *,
    settings: Settings,
    seeds: list[dict[str, Any]],
    grid: DomainGrid,
    profile_id: str,
    field_constants: dict[str, Any],
    horizons_h: list[int],
    zones: list[dict[str, Any]],
    run_seed: int,
    field_ref: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the engine and return (public metric, replayable artifact).

    The return shape matches :func:`run_synthetic_transport` so ``intersect_zone``
    works against either engine without branching.
    """

    request = build_request(
        seeds=seeds,
        grid=grid,
        profile_id=profile_id,
        field_constants=field_constants,
        horizons_h=horizons_h,
        zones=zones,
        run_seed=run_seed,
        field_ref=field_ref,
    )
    result = invoke_bridge(settings, request)
    step_minutes = result["time_step_minutes"]
    horizons = sorted(horizons_h)
    total_steps = max(horizons) * 60 // step_minutes
    members = _members_from_particles(result, grid, total_steps)
    released = len(members)

    snapshots: dict[str, list[dict[str, Any]]] = {}
    envelopes: dict[str, dict[str, Any]] = {}
    horizon_summary: dict[str, dict[str, Any]] = {}
    for hour in horizons:
        step_index = hour * 60 // step_minutes
        live = [member for member in members if member["last_step_index"] >= step_index]
        positions = []
        for member in live:
            lon, lat = member["trajectory"][step_index]
            positions.append({"member_index": member["member_index"], "lon": lon, "lat": lat})
        snapshots[str(hour)] = positions
        occupied = sorted(
            {
                cell_id
                for position in positions
                if (cell_id := grid.cell_id(position["lon"], position["lat"])) is not None
            }
        )
        bounds = [grid.cell_bbox(cell_id) for cell_id in occupied]
        envelopes[str(hour)] = {
            "occupied_cells": occupied,
            "bbox": {
                "lon_min": min(item["lon_min"] for item in bounds),
                "lon_max": max(item["lon_max"] for item in bounds),
                "lat_min": min(item["lat_min"] for item in bounds),
                "lat_max": max(item["lat_max"] for item in bounds),
            }
            if bounds
            else None,
            "valid_members": len(positions),
        }
        horizon_summary[str(hour)] = {
            "released": released,
            "valid": len(positions),
            "terminated_by": {
                reason: sum(
                    member["terminated_reason"] == reason
                    and member["terminated_at_minutes"] <= hour * 60
                    for member in members
                )
                for reason in _TERMINATION_REASONS
            },
        }

    reproducibility = {
        "run_seed": run_seed,
        "rng_algorithm": "mulberry32",
        "quantization": {"coordinate_deg": 1e-7, "physical": 1e-6},
        "float_policy": "float64_midpoint_fixed_step_sorted_index",
        "reproducibility_class": "exact_same_engine_bundle",
        "engine_bundle_checksum": bundle_checksum(bridge_path(settings)),
    }
    public = {
        "profile_id": profile_id,
        "engine": ENGINE_ID,
        "field_constants": {
            "u_ms": field_constants["u_ms"],
            "v_ms": field_constants["v_ms"],
            "spread_parameterization": field_constants.get("spread_parameterization"),
            "sigma_ms": field_constants.get("sigma_ms"),
        },
        "released": released,
        "horizon_summary": horizon_summary,
        "envelopes": envelopes,
        "gate_connectivity": result["gates"],
        "gate_geometry": {
            "kind": "center",
            "width_m": result["gate_width_m"],
            "bearing_deg": result["gate_bearing_deg"],
            "bearing_basis": "perpendicular_to_synthetic_field",
            "min_depth_m": GATE_MIN_DEPTH_M,
            "max_depth_m": GATE_MAX_DEPTH_M,
        },
        "ensemble": request["ensemble"],
        "navigability": {
            **request["navigability"],
            "note": "flat synthetic bathymetry; land and real depth are not represented",
        },
        "classification": result["classification"],
        "disclaimer": result["disclaimer"],
        "diagnostics": result["diagnostics"],
        "physical_realism": "none",
        "coastline_basis": "synthetic_flat_bathymetry",
        "orchestrator": "mock",
        "reproducibility": reproducibility,
    }
    artifact = {
        "profile_id": profile_id,
        "engine": ENGINE_ID,
        "horizons_h": horizons,
        "snapshots": snapshots,
        "members": members,
        "run_seed": run_seed,
        "gate_connectivity": result["gates"],
        "reproducibility": reproducibility,
    }
    return public, artifact
