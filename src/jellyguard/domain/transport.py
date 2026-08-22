from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

SYNTHETIC_PROFILES = {
    "B0_hold": {"u_ms": 0.0, "v_ms": 0.0, "spread_parameterization": None},
    "B2_current_only": {"u_ms": -0.12, "v_ms": 0.04, "spread_parameterization": None},
    "B3": {
        "u_ms": -0.12,
        "v_ms": 0.04,
        "sigma_ms": 0.03,
        "spread_parameterization": "synthetic_velocity_perturbation",
    },
}


@dataclass(frozen=True)
class DomainGrid:
    domain_id: str
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float
    spacing_deg: float

    @classmethod
    def from_fixture(cls, fixture: dict[str, Any]) -> DomainGrid:
        bbox = fixture["bbox"]
        return cls(
            domain_id=fixture["domain_id"],
            lon_min=bbox["lon_min"],
            lon_max=bbox["lon_max"],
            lat_min=bbox["lat_min"],
            lat_max=bbox["lat_max"],
            spacing_deg=fixture["spacing_deg"],
        )

    def contains(self, lon: float, lat: float) -> bool:
        return self.lon_min <= lon <= self.lon_max and self.lat_min <= lat <= self.lat_max

    def cell_id(self, lon: float, lat: float) -> str | None:
        if not self.contains(lon, lat):
            return None
        col = min(
            int((lon - self.lon_min) / self.spacing_deg),
            math.ceil((self.lon_max - self.lon_min) / self.spacing_deg) - 1,
        )
        row = min(
            int((lat - self.lat_min) / self.spacing_deg),
            math.ceil((self.lat_max - self.lat_min) / self.spacing_deg) - 1,
        )
        return f"r{row:02d}c{col:02d}"

    def cell_bbox(self, cell_id: str) -> dict[str, float]:
        row_text, col_text = cell_id.split("c", 1)
        row = int(row_text.removeprefix("r"))
        col = int(col_text)
        lon_min = self.lon_min + col * self.spacing_deg
        lat_min = self.lat_min + row * self.spacing_deg
        return {
            "lon_min": lon_min,
            "lon_max": min(lon_min + self.spacing_deg, self.lon_max),
            "lat_min": lat_min,
            "lat_max": min(lat_min + self.spacing_deg, self.lat_max),
        }

    def neighbor_cells(self, center: str, mode: str) -> set[str]:
        row_text, col_text = center.split("c", 1)
        row = int(row_text.removeprefix("r"))
        col = int(col_text)
        offsets = {(0, 0)}
        if mode in {"edge4", "edge8"}:
            offsets |= {(-1, 0), (1, 0), (0, -1), (0, 1)}
        if mode == "edge8":
            offsets |= {(-1, -1), (-1, 1), (1, -1), (1, 1)}
        cells = set()
        for row_delta, col_delta in offsets:
            candidate = f"r{row + row_delta:02d}c{col + col_delta:02d}"
            bbox = self.cell_bbox(candidate)
            if self.contains(bbox["lon_min"], bbox["lat_min"]):
                cells.add(candidate)
        return cells


def parse_synthetic_field_ref(field_ref: str, domain_id: str) -> str:
    if not field_ref.startswith("synthetic:"):
        raise ValueError("field_ref must use the four-part synthetic format")
    remainder = field_ref.removeprefix("synthetic:")
    grid_and_profile, separator, validity = remainder.partition(":")
    if not separator or ":" not in validity:
        raise ValueError("field_ref must include issued_at and valid_at")
    prefix = f"{domain_id}."
    if not grid_and_profile.startswith(prefix):
        raise LookupError("field_ref grid does not match the Hanul synthetic domain")
    profile = grid_and_profile.removeprefix(prefix)
    if profile not in SYNTHETIC_PROFILES:
        raise ValueError("unknown synthetic profile")
    return profile


def deterministic_run_seed(payload: dict[str, Any]) -> int:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return int.from_bytes(hashlib.blake2b(encoded, digest_size=8).digest(), "big")


def _advance_rk4(
    lon: float,
    lat: float,
    u_ms: float,
    v_ms: float,
    dt_seconds: float,
) -> tuple[float, float]:
    def derivative(at_lat: float) -> tuple[float, float]:
        latitude_radians = math.radians(at_lat)
        return (
            u_ms / (111_320.0 * math.cos(latitude_radians)),
            v_ms / 111_320.0,
        )

    k1_lon, k1_lat = derivative(lat)
    k2_lon, k2_lat = derivative(lat + 0.5 * dt_seconds * k1_lat)
    k3_lon, k3_lat = derivative(lat + 0.5 * dt_seconds * k2_lat)
    k4_lon, k4_lat = derivative(lat + dt_seconds * k3_lat)
    return (
        lon + (dt_seconds / 6.0) * (k1_lon + 2 * k2_lon + 2 * k3_lon + k4_lon),
        lat + (dt_seconds / 6.0) * (k1_lat + 2 * k2_lat + 2 * k3_lat + k4_lat),
    )


def run_synthetic_transport(
    *,
    seeds: list[dict[str, Any]],
    grid: DomainGrid,
    profile_id: str,
    horizons_h: list[int],
    run_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = SYNTHETIC_PROFILES[profile_id]
    members: list[dict[str, Any]] = []
    for seed in sorted(seeds, key=lambda item: item["seed_id"]):
        lon, lat = seed["geometry"]["coordinates"]
        for row in range(5):
            for col in range(5):
                member_lon = lon + (col - 2) * 0.005
                member_lat = lat + (row - 2) * 0.005
                members.append(
                    {
                        "member_index": len(members),
                        "seed_id": seed["seed_id"],
                        "lon": member_lon,
                        "lat": member_lat,
                        "terminated_reason": None,
                        "terminated_at_minutes": None,
                        "visited_cells": {},
                        "trajectory": [[member_lon, member_lat]],
                    }
                )

    member_rngs: list[np.random.Generator] | None = None
    if profile_id == "B3":
        member_rngs = [
            np.random.Generator(np.random.PCG64(child_sequence))
            for child_sequence in np.random.SeedSequence(run_seed).spawn(len(members))
        ]

    horizon_steps = {hour: hour * 12 for hour in horizons_h}
    snapshots: dict[str, list[dict[str, Any]]] = {}
    dt_seconds = 300.0
    maximum_step = max(horizon_steps.values())
    for step in range(maximum_step + 1):
        elapsed_minutes = step * 5
        for member in members:
            if member["terminated_reason"] is not None:
                continue
            cell_id = grid.cell_id(member["lon"], member["lat"])
            if cell_id is None:
                member["terminated_reason"] = "out_of_domain"
                member["terminated_at_minutes"] = elapsed_minutes
                continue
            member["visited_cells"].setdefault(cell_id, elapsed_minutes)

        for hour, horizon_step in horizon_steps.items():
            if step == horizon_step:
                snapshots[str(hour)] = [
                    {
                        "member_index": member["member_index"],
                        "lon": member["lon"],
                        "lat": member["lat"],
                    }
                    for member in members
                    if member["terminated_reason"] is None
                ]
        if step == maximum_step:
            break

        for member in members:
            if member["terminated_reason"] is not None:
                continue
            u_ms = profile["u_ms"]
            v_ms = profile["v_ms"]
            if member_rngs is not None:
                member_rng = member_rngs[member["member_index"]]
                u_ms += float(member_rng.normal(0.0, profile["sigma_ms"]))
                v_ms += float(member_rng.normal(0.0, profile["sigma_ms"]))
            member["lon"], member["lat"] = _advance_rk4(
                member["lon"], member["lat"], u_ms, v_ms, dt_seconds
            )
            member["trajectory"].append([member["lon"], member["lat"]])

    envelopes: dict[str, dict[str, Any]] = {}
    horizon_summary: dict[str, dict[str, Any]] = {}
    released = len(members)
    for hour in horizons_h:
        positions = snapshots[str(hour)]
        occupied_cells = sorted(
            {
                cell_id
                for position in positions
                if (cell_id := grid.cell_id(position["lon"], position["lat"])) is not None
            }
        )
        cell_bounds = [grid.cell_bbox(cell_id) for cell_id in occupied_cells]
        envelope_bbox = None
        if cell_bounds:
            envelope_bbox = {
                "lon_min": min(item["lon_min"] for item in cell_bounds),
                "lon_max": max(item["lon_max"] for item in cell_bounds),
                "lat_min": min(item["lat_min"] for item in cell_bounds),
                "lat_max": max(item["lat_max"] for item in cell_bounds),
            }
        terminated_by = {
            reason: sum(
                member["terminated_reason"] == reason
                and member["terminated_at_minutes"] <= hour * 60
                for member in members
            )
            for reason in ("out_of_domain", "forecast_unavailable", "field_missing")
        }
        envelopes[str(hour)] = {
            "occupied_cells": occupied_cells,
            "bbox": envelope_bbox,
            "valid_members": len(positions),
        }
        horizon_summary[str(hour)] = {
            "released": released,
            "valid": len(positions),
            "terminated_by": terminated_by,
        }

    reproducibility = {
        "run_seed": run_seed,
        "rng_algorithm": "PCG64",
        "quantization": {"coordinate_deg": 1e-7, "physical": 1e-6},
        "float_policy": "float64_rk4_fixed_no_parallel_reduce_sorted_index",
        "reproducibility_class": "quantized_cross_env",
    }
    public = {
        "profile_id": profile_id,
        "field_constants": {
            "u_ms": profile["u_ms"],
            "v_ms": profile["v_ms"],
            "spread_parameterization": profile.get("spread_parameterization"),
            "sigma_ms": profile.get("sigma_ms"),
        },
        "released": released,
        "horizon_summary": horizon_summary,
        "envelopes": envelopes,
        "physical_realism": "none",
        "coastline_basis": "none",
        "orchestrator": "mock",
        "reproducibility": reproducibility,
    }
    artifact = {
        "profile_id": profile_id,
        "horizons_h": horizons_h,
        "snapshots": snapshots,
        "members": members,
        "run_seed": run_seed,
        "reproducibility": reproducibility,
    }
    return public, artifact
