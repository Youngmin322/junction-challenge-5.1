from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
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

    def expanded(self, factor: float) -> DomainGrid:
        """Grow the window by ``factor`` about its centre, keeping the cell spacing.

        Spacing stays fixed so the expanded run resolves the flow exactly as the first
        attempt did; only the computation window changes, never the sampling scale.
        """
        lon_pad = (self.lon_max - self.lon_min) * factor / 2.0
        lat_pad = (self.lat_max - self.lat_min) * factor / 2.0
        return DomainGrid(
            domain_id=self.domain_id,
            lon_min=self.lon_min - lon_pad,
            lon_max=self.lon_max + lon_pad,
            lat_min=self.lat_min - lat_pad,
            lat_max=self.lat_max + lat_pad,
            spacing_deg=self.spacing_deg,
        )

    def as_bbox(self) -> dict[str, float]:
        return {
            "lon_min": self.lon_min,
            "lon_max": self.lon_max,
            "lat_min": self.lat_min,
            "lat_max": self.lat_max,
        }

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


def _integrate(
    *,
    members: list[dict[str, Any]],
    grid: DomainGrid,
    horizons_h: list[int],
    velocity_at: Callable[[dict[str, Any], float, float, float], tuple[float, float] | None],
) -> dict[str, list[dict[str, Any]]]:
    """Step every live member forward, terminating rather than inventing missing velocity.

    ``velocity_at`` returns ``None`` when the field cannot answer for that position and
    time. The member is then terminated with ``field_missing`` instead of being carried
    forward on a nearest neighbour value.
    """
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
            velocity = velocity_at(member, member["lon"], member["lat"], step * dt_seconds)
            if velocity is None:
                member["terminated_reason"] = "field_missing"
                member["terminated_at_minutes"] = elapsed_minutes
                continue
            u_ms, v_ms = velocity
            member["lon"], member["lat"] = _advance_rk4(
                member["lon"], member["lat"], u_ms, v_ms, dt_seconds
            )
            member["trajectory"].append([member["lon"], member["lat"]])
    return snapshots


def _seed_members(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spread each seed into a fixed 5x5 member cloud around its reported position."""
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
    return members


def _summarize(
    *,
    members: list[dict[str, Any]],
    snapshots: dict[str, list[dict[str, Any]]],
    grid: DomainGrid,
    horizons_h: list[int],
) -> tuple[dict[str, Any], dict[str, Any], int]:
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

    return envelopes, horizon_summary, released


def run_synthetic_transport(
    *,
    seeds: list[dict[str, Any]],
    grid: DomainGrid,
    profile_id: str,
    horizons_h: list[int],
    run_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = SYNTHETIC_PROFILES[profile_id]
    members = _seed_members(seeds)

    member_rngs: list[np.random.Generator] | None = None
    if profile_id == "B3":
        member_rngs = [
            np.random.Generator(np.random.PCG64(child_sequence))
            for child_sequence in np.random.SeedSequence(run_seed).spawn(len(members))
        ]

    def velocity_at(member: dict[str, Any], _lon: float, _lat: float, _seconds: float):
        u_ms = profile["u_ms"]
        v_ms = profile["v_ms"]
        if member_rngs is not None:
            member_rng = member_rngs[member["member_index"]]
            u_ms += float(member_rng.normal(0.0, profile["sigma_ms"]))
            v_ms += float(member_rng.normal(0.0, profile["sigma_ms"]))
        return u_ms, v_ms

    snapshots = _integrate(
        members=members,
        grid=grid,
        horizons_h=horizons_h,
        velocity_at=velocity_at,
    )

    envelopes, horizon_summary, released = _summarize(
        members=members,
        snapshots=snapshots,
        grid=grid,
        horizons_h=horizons_h,
    )

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


@dataclass(frozen=True)
class MeasuredField:
    """A time-varying velocity field sampled from provider rows, with holes preserved.

    Bilinear interpolation needs all four surrounding grid points. When any of them is
    absent the sample is refused rather than filled from the nearest neighbour, because a
    filled hole is indistinguishable from measured water once it reaches a trajectory.
    """

    field_id: str
    lats: tuple[float, ...]
    lons: tuple[float, ...]
    times: tuple[float, ...]
    samples: dict[tuple[float, float, float], tuple[float, float]]
    convention: str
    start_epoch: float

    @classmethod
    def from_rows(
        cls,
        rows: list[dict[str, Any]],
        *,
        field_id: str,
        convention: str,
    ) -> MeasuredField:
        if convention not in {"TOWARD", "FROM"}:
            raise ValueError("direction convention must be settled before sampling a field")
        samples: dict[tuple[float, float, float], tuple[float, float]] = {}
        for row in rows:
            lat, lon = row.get("lat"), row.get("lon")
            direction, speed = row.get("current_direction"), row.get("current_speed")
            epoch = _epoch_seconds(row.get("valid_at"))
            if None in (lat, lon, direction, speed, epoch):
                continue
            radians = math.radians(float(direction))
            u = float(speed) * math.sin(radians)
            v = float(speed) * math.cos(radians)
            if convention == "FROM":
                u, v = -u, -v
            samples[(float(lat), float(lon), epoch)] = (u, v)
        if not samples:
            raise ValueError("no usable velocity rows")
        lats = tuple(sorted({key[0] for key in samples}))
        lons = tuple(sorted({key[1] for key in samples}))
        times = tuple(sorted({key[2] for key in samples}))
        return cls(
            field_id=field_id,
            lats=lats,
            lons=lons,
            times=times,
            samples=samples,
            convention=convention,
            start_epoch=times[0],
        )

    @property
    def covered_bbox(self) -> dict[str, float]:
        """The footprint the provider actually delivered rows for.

        This is the hard limit for window expansion: outside it there is nothing to
        interpolate, so a wider grid would only relabel ``field_missing`` particles as
        in-domain without adding a single measured value.
        """
        return {
            "lon_min": self.lons[0],
            "lon_max": self.lons[-1],
            "lat_min": self.lats[0],
            "lat_max": self.lats[-1],
        }

    def covers_grid(self, grid: DomainGrid) -> bool:
        bbox = self.covered_bbox
        return (
            grid.lon_min >= bbox["lon_min"]
            and grid.lon_max <= bbox["lon_max"]
            and grid.lat_min >= bbox["lat_min"]
            and grid.lat_max <= bbox["lat_max"]
        )

    def sample(self, lon: float, lat: float, elapsed_seconds: float) -> tuple[float, float] | None:
        when = self.start_epoch + elapsed_seconds
        time_bracket = _bracket(self.times, when)
        lat_bracket = _bracket(self.lats, lat)
        lon_bracket = _bracket(self.lons, lon)
        if time_bracket is None or lat_bracket is None or lon_bracket is None:
            return None
        (time_low, time_high, time_weight) = time_bracket
        (lat_low, lat_high, lat_weight) = lat_bracket
        (lon_low, lon_high, lon_weight) = lon_bracket

        corners = []
        for stamp in (time_low, time_high):
            plane = []
            for corner_lat in (lat_low, lat_high):
                for corner_lon in (lon_low, lon_high):
                    value = self.samples.get((corner_lat, corner_lon, stamp))
                    if value is None:
                        return None
                    plane.append(value)
            corners.append(plane)

        def blend(plane: list[tuple[float, float]]) -> tuple[float, float]:
            south = _mix(plane[0], plane[1], lon_weight)
            north = _mix(plane[2], plane[3], lon_weight)
            return _mix(south, north, lat_weight)

        return _mix(blend(corners[0]), blend(corners[1]), time_weight)


# How many arrows the offline dashboard asks for. Enough to show the shape of the flow
# across the domain, few enough that the arrows stay separable at screen size and the
# bootstrap payload stays a projection rather than a copy of the field.
DASHBOARD_VECTOR_LIMIT = 24


def downsample_field_vectors(
    field: MeasuredField, *, limit: int = DASHBOARD_VECTOR_LIMIT
) -> list[dict[str, float]]:
    """Thin a measured field into a handful of representative arrows.

    Sampling by striding both axes keeps the arrows spread over the whole covered area.
    Taking the first N rows instead would crowd every arrow into one corner of the grid and
    let a viewer read a local eddy as the domain-wide flow.

    The components come from ``MeasuredField``, so the direction convention has already been
    applied here; there is deliberately no second place that turns a bearing into u/v.
    """
    if limit < 1 or not field.times:
        return []
    when = field.times[0]
    side = max(1, math.isqrt(limit))
    lat_stride = max(1, math.ceil(len(field.lats) / side))
    lon_stride = max(1, math.ceil(len(field.lons) / side))
    vectors: list[dict[str, float]] = []
    for lat in field.lats[::lat_stride]:
        for lon in field.lons[::lon_stride]:
            sample = field.samples.get((lat, lon, when))
            if sample is None:
                # A hole in the field stays a hole: no nearest-neighbour fill.
                continue
            u_ms, v_ms = sample
            vectors.append(
                {
                    "lon": round(lon, 6),
                    "lat": round(lat, 6),
                    "u_ms": round(u_ms, 4),
                    "v_ms": round(v_ms, 4),
                    "speed_ms": round(math.hypot(u_ms, v_ms), 4),
                    "bearing_deg_toward": round(math.degrees(math.atan2(u_ms, v_ms)) % 360.0, 2),
                }
            )
            if len(vectors) >= limit:
                return vectors
    return vectors


def _mix(low: tuple[float, float], high: tuple[float, float], weight: float) -> tuple[float, float]:
    return (
        low[0] + (high[0] - low[0]) * weight,
        low[1] + (high[1] - low[1]) * weight,
    )


def _bracket(values: tuple[float, ...], target: float) -> tuple[float, float, float] | None:
    if not values or target < values[0] or target > values[-1]:
        return None
    for index in range(len(values) - 1):
        low, high = values[index], values[index + 1]
        if low <= target <= high:
            span = high - low
            return low, high, 0.0 if span == 0 else (target - low) / span
    return values[-1], values[-1], 0.0


def _epoch_seconds(stamp: Any) -> float | None:
    from datetime import datetime

    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp)).timestamp()
    except ValueError:
        return None


LIVE_FIELD_PREFIX = "live:"

# Above this share of released members leaving the grid, the computation window is too
# small to describe the flow and the result must say so instead of reporting a thinned
# envelope as if it were the whole cloud.
DOMAIN_EXIT_TOLERANCE = 0.01

# When the tolerance is exceeded the window is widened by this share about its centre and
# the run is repeated, at most this many times. Neither number is a scientific threshold:
# they are versioned engineering defaults chosen so that a truncated computation window is
# never hidden, and the values actually used are written into every run result.
DOMAIN_EXPANSION_FACTOR = 0.25
DOMAIN_EXPANSION_MAX_ATTEMPTS = 4


def parse_live_field_ref(field_ref: str, domain_id: str) -> str:
    """Return the source id carried by a four-part live field reference."""
    if not field_ref.startswith(LIVE_FIELD_PREFIX):
        raise ValueError("field_ref must use the four-part live format")
    remainder = field_ref.removeprefix(LIVE_FIELD_PREFIX)
    grid_and_source, separator, validity = remainder.partition(":")
    if not separator or ":" not in validity:
        raise ValueError("field_ref must include issued_at and valid_at")
    prefix = f"{domain_id}."
    if not grid_and_source.startswith(prefix):
        raise LookupError("field_ref grid does not match the Hanul domain")
    source_id = grid_and_source.removeprefix(prefix)
    if not source_id:
        raise ValueError("field_ref is missing a source id")
    return source_id


def _measured_attempt(
    *,
    seeds: list[dict[str, Any]],
    grid: DomainGrid,
    field: MeasuredField,
    horizons_h: list[int],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Run one integration over one candidate window and report how much of it leaked out."""
    members = _seed_members(seeds)

    def velocity_at(_member: dict[str, Any], lon: float, lat: float, seconds: float):
        return field.sample(lon, lat, seconds)

    snapshots = _integrate(
        members=members,
        grid=grid,
        horizons_h=horizons_h,
        velocity_at=velocity_at,
    )
    envelopes, horizon_summary, released = _summarize(
        members=members,
        snapshots=snapshots,
        grid=grid,
        horizons_h=horizons_h,
    )
    exit_fraction = {
        hour: (
            summary["terminated_by"]["out_of_domain"] / summary["released"]
            if summary["released"]
            else 0.0
        )
        for hour, summary in horizon_summary.items()
    }
    outcome = {
        "envelopes": envelopes,
        "horizon_summary": horizon_summary,
        "released": released,
        "exit_fraction": exit_fraction,
        "insufficient": sorted(
            int(hour) for hour, share in exit_fraction.items() if share > DOMAIN_EXIT_TOLERANCE
        ),
    }
    return outcome, snapshots, members


def run_measured_transport(
    *,
    seeds: list[dict[str, Any]],
    grid: DomainGrid,
    field: MeasuredField,
    horizons_h: list[int],
    run_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Advect seeds through a measured field, with no stochastic spread.

    A single deterministic forecast carries no spread information of its own, so members
    differ only by their release position. Calling the result an ensemble would imply an
    uncertainty estimate that this field cannot support.

    The bbox here is a computation window, not a risk area: when too much of the cloud
    leaves it before the requested horizon the window is widened and the run repeated,
    because a window that is too small silently reports a thinned envelope as if it were the
    whole cloud. Expansion never re-fetches — it only re-uses the field already loaded, so
    the provider footprint bounds how far it can go.
    """
    attempt_grid = grid
    attempt_exit_fractions: list[dict[str, Any]] = []
    stopped_reason: str | None = None
    attempts = 0
    while True:
        attempts += 1
        outcome, snapshots, members = _measured_attempt(
            seeds=seeds,
            grid=attempt_grid,
            field=field,
            horizons_h=horizons_h,
        )
        attempt_exit_fractions.append(
            {
                "attempt": attempts,
                "bbox": attempt_grid.as_bbox(),
                "exit_fraction": {
                    hour: round(share, 4) for hour, share in outcome["exit_fraction"].items()
                },
                "insufficient_horizons": outcome["insufficient"],
            }
        )
        if not outcome["insufficient"]:
            break
        candidate = attempt_grid.expanded(DOMAIN_EXPANSION_FACTOR)
        if not field.covers_grid(candidate):
            # Widening past the measured footprint would only turn field_missing members
            # into in-domain ones without adding measured water. Stop and say so.
            stopped_reason = "field_footprint_limit"
            break
        if attempts > DOMAIN_EXPANSION_MAX_ATTEMPTS:
            stopped_reason = "expansion_attempt_cap"
            break
        attempt_grid = candidate

    reproducibility = {
        "run_seed": run_seed,
        "rng_algorithm": "none",
        "quantization": {"coordinate_deg": 1e-7, "physical": 1e-6},
        "float_policy": "float64_rk4_fixed_no_parallel_reduce_sorted_index",
        "reproducibility_class": "quantized_cross_env",
    }
    domain_expansion = {
        "attempts": attempts,
        "expansions_applied": attempts - 1,
        "max_attempts": DOMAIN_EXPANSION_MAX_ATTEMPTS,
        "expansion_factor": DOMAIN_EXPANSION_FACTOR,
        "tolerance": DOMAIN_EXIT_TOLERANCE,
        "initial_bbox": grid.as_bbox(),
        "final_bbox": attempt_grid.as_bbox(),
        "field_covered_bbox": field.covered_bbox,
        "attempt_exit_fractions": attempt_exit_fractions,
        "stopped_reason": stopped_reason,
        "resolved": not outcome["insufficient"],
    }
    public = {
        "profile_id": f"measured:{field.field_id}",
        "domain_exit_fraction": {
            hour: round(share, 4) for hour, share in outcome["exit_fraction"].items()
        },
        "domain_exit_tolerance": DOMAIN_EXIT_TOLERANCE,
        "domain_insufficient_horizons": outcome["insufficient"],
        "domain_expansion": domain_expansion,
        "field_constants": None,
        "field_source": {
            "field_id": field.field_id,
            "crdir_convention": field.convention,
            "convention_basis": "check_based_provider_unconfirmed",
            "cell_count": len(field.samples) // max(len(field.times), 1),
            "timestep_count": len(field.times),
            "interpolation": "bilinear_space_linear_time_no_gap_fill",
        },
        "released": outcome["released"],
        "horizon_summary": outcome["horizon_summary"],
        "envelopes": outcome["envelopes"],
        "physical_realism": "surface_only_measured_field",
        "coastline_basis": "none",
        "spread_parameterization": None,
        "orchestrator": "mock",
        "reproducibility": reproducibility,
    }
    artifact = {
        "profile_id": public["profile_id"],
        "horizons_h": horizons_h,
        "snapshots": snapshots,
        "members": members,
        "run_seed": run_seed,
        "domain_expansion": domain_expansion,
        "reproducibility": reproducibility,
    }
    return public, artifact
