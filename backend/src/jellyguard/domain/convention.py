"""Decide whether a provider's flow-direction field means toward or from.

KHOA publishes ``crdir`` in degrees but never states, in either the API guide or the
dataset page, whether the angle is the direction the water flows *toward* or the
direction it comes *from*. The two readings are exactly 180 degrees apart, so guessing
produces trajectories that look plausible and are completely wrong.

The check here does not guess. Temperature is carried by the flow, so the first-order
advection balance must hold:

    dT/dt ~= -(u * dT/dx + v * dT/dy)

Flipping the convention flips the sign of ``u`` and ``v``, and therefore the sign of the
correlation between the observed temperature tendency and the advective term. Only one
reading can correlate positively, which makes this a discriminating test rather than a
plausibility argument.

Two KHOA-published documents state the institution's general current-direction
convention (not this specific API's field, which stays undocumented): the agency's own
"해양관측" overview page, and Article 5 of its 해양관측 업무규정 (Ocean Observation Work
Regulation). Both say current direction is TOWARD. This is corroboration, not a
substitute for the check -- it is recorded separately as ``institutional_corroboration``
and never flips ``provider_documented``, which stays about this specific API's own
spec sheet, which still says nothing.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

TOWARD = "TOWARD"
FROM = "FROM"
INCONCLUSIVE = "INCONCLUSIVE"

MIN_SAMPLES = 200
MIN_ABS_CORRELATION = 0.15

# KHOA's general convention for current direction, per two independent institutional
# documents (not this API's own spec, which remains silent -- see module docstring).
# This is fixed regardless of what any single fetch measures: if a check ever disagrees
# with it, that is a conflict worth surfacing, not something this constant should chase.
KHOA_INSTITUTIONAL_CONVENTION = TOWARD
KHOA_INSTITUTIONAL_CITATIONS = (
    {
        "title": "국립해양조사원 업무소개 - 해양관측",
        "url": "https://www.khoa.go.kr/kcom/cnt/selectContentsPage.do?cntId=25402000",
        "quote": (
            "해류에서 유향이 북동류라는 것은 남서쪽에서 북동쪽으로 흐른다는 의미이나, "
            "바람에서 풍향이 북동풍은 북동쪽에서 불어온다는 의미"
        ),
    },
    {
        "title": "해양관측 업무규정 제5조(해양관측기준)",
        "url": "https://www.ulex.co.kr/%EB%B2%95%EB%A5%A0/2100000067629-2082328-%ED%95%B4%EC%96%91",
        "quote": "유향/파향 0°는 북쪽으로 진행을 의미",
    },
)

METERS_PER_DEGREE_LAT = 110_540.0
METERS_PER_DEGREE_LON_EQUATOR = 111_320.0


def verify_flow_direction_convention(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the convention verdict for one fetched field, with its evidence."""
    cells = _index_cells(rows)
    lats = sorted({lat for lat, _ in cells})
    lons = sorted({lon for _, lon in cells})
    times = sorted({time for series in cells.values() for time in series})

    tendency: list[float] = []
    advection_toward: list[float] = []
    northward = 0
    southward = 0

    for (lat, lon), series in cells.items():
        for index in range(1, len(times) - 1):
            before, now, after = times[index - 1], times[index], times[index + 1]
            if not all(stamp in series for stamp in (before, now, after)):
                continue
            direction, speed, _ = series[now]
            if direction is None or speed is None:
                continue
            u, v = _to_components(direction, speed)
            northward += v > 0
            southward += v < 0
            step_seconds = _seconds_between(before, after)
            if step_seconds is None or step_seconds <= 0:
                continue
            temperature_tendency = (series[after][2] - series[before][2]) / step_seconds
            gradient = _temperature_gradient(cells, lats, lons, lat, lon, now)
            if gradient is None:
                continue
            gradient_x, gradient_y = gradient
            tendency.append(temperature_tendency)
            advection_toward.append(-(u * gradient_x + v * gradient_y))

    correlation = _correlation(tendency, advection_toward)
    verdict = _verdict(correlation, len(tendency))
    return {
        "verdict": verdict,
        "method": "temperature_advection_sign_test",
        "correlation_toward": None if correlation is None else round(correlation, 4),
        "correlation_from": None if correlation is None else round(-correlation, 4),
        "sample_size": len(tendency),
        "minimum_sample_size": MIN_SAMPLES,
        "minimum_abs_correlation": MIN_ABS_CORRELATION,
        "northward_fraction": (
            round(northward / (northward + southward), 4) if northward + southward else None
        ),
        "provider_documented": False,
        "basis": "check_based_provider_unconfirmed" if verdict != INCONCLUSIVE else "none",
        "institutional_corroboration": _institutional_corroboration(verdict),
    }


def _verdict(correlation: float | None, sample_size: int) -> str:
    if correlation is None or sample_size < MIN_SAMPLES:
        return INCONCLUSIVE
    if abs(correlation) < MIN_ABS_CORRELATION:
        return INCONCLUSIVE
    return TOWARD if correlation > 0 else FROM


def _institutional_corroboration(verdict: str) -> dict[str, Any]:
    """Compare this fetch's data-driven verdict against KHOA's stated general convention.

    A match is corroboration, not proof -- it still is not this API's own spec sheet. A
    mismatch would mean the check and the institution's own documents disagree, which is
    worth a visible flag rather than quietly trusting either one.
    """
    if verdict == INCONCLUSIVE:
        return {
            "status": "not_applicable",
            "institutional_convention": KHOA_INSTITUTIONAL_CONVENTION,
            "citations": list(KHOA_INSTITUTIONAL_CITATIONS),
        }
    status = "corroborated" if verdict == KHOA_INSTITUTIONAL_CONVENTION else "conflicting"
    return {
        "status": status,
        "institutional_convention": KHOA_INSTITUTIONAL_CONVENTION,
        "citations": list(KHOA_INSTITUTIONAL_CITATIONS),
    }


def _index_cells(rows: list[dict[str, Any]]) -> dict[tuple[float, float], dict[str, tuple]]:
    cells: dict[tuple[float, float], dict[str, tuple]] = {}
    for row in rows:
        lat, lon, stamp = row.get("lat"), row.get("lon"), row.get("valid_at")
        temperature = row.get("water_temperature")
        if lat is None or lon is None or stamp is None or temperature is None:
            continue
        cells.setdefault((lat, lon), {})[stamp] = (
            row.get("current_direction"),
            row.get("current_speed"),
            temperature,
        )
    return cells


def _to_components(direction_degrees: float, speed: float) -> tuple[float, float]:
    """Convert a compass bearing under the toward reading into east/north components."""
    radians = math.radians(direction_degrees)
    return speed * math.sin(radians), speed * math.cos(radians)


def _seconds_between(before: str, after: str) -> float | None:
    from datetime import datetime

    try:
        start = datetime.fromisoformat(before)
        end = datetime.fromisoformat(after)
    except ValueError:
        return None
    return (end - start).total_seconds()


def _temperature_gradient(
    cells: dict[tuple[float, float], dict[str, tuple]],
    lats: list[float],
    lons: list[float],
    lat: float,
    lon: float,
    stamp: str,
) -> tuple[float, float] | None:
    def temperature(at_lat: float | None, at_lon: float | None) -> float | None:
        if at_lat is None or at_lon is None:
            return None
        entry = cells.get((at_lat, at_lon), {}).get(stamp)
        return None if entry is None else entry[2]

    here = temperature(lat, lon)
    if here is None:
        return None
    lat_index, lon_index = lats.index(lat), lons.index(lon)
    west = lons[lon_index - 1] if lon_index > 0 else None
    east = lons[lon_index + 1] if lon_index + 1 < len(lons) else None
    south = lats[lat_index - 1] if lat_index > 0 else None
    north = lats[lat_index + 1] if lat_index + 1 < len(lats) else None

    gradient_x = _difference(
        temperature(lat, west), here, temperature(lat, east), _meters_x(lat, west, lon, east)
    )
    gradient_y = _difference(
        temperature(south, lon), here, temperature(north, lon), _meters_y(south, lat, north)
    )
    if gradient_x is None or gradient_y is None:
        return None
    return gradient_x, gradient_y


def _difference(
    low: float | None, here: float, high: float | None, spans: tuple[float, float, float]
) -> float | None:
    both, low_span, high_span = spans
    if low is not None and high is not None and both:
        return (high - low) / both
    if high is not None and high_span:
        return (high - here) / high_span
    if low is not None and low_span:
        return (here - low) / low_span
    return None


def _meters_x(
    lat: float, west: float | None, lon: float, east: float | None
) -> tuple[float, float, float]:
    scale = METERS_PER_DEGREE_LON_EQUATOR * math.cos(math.radians(lat))
    both = (east - west) * scale if west is not None and east is not None else 0.0
    low = (lon - west) * scale if west is not None else 0.0
    high = (east - lon) * scale if east is not None else 0.0
    return both, low, high


def _meters_y(south: float | None, lat: float, north: float | None) -> tuple[float, float, float]:
    both = (
        (north - south) * METERS_PER_DEGREE_LAT if south is not None and north is not None else 0.0
    )
    low = (lat - south) * METERS_PER_DEGREE_LAT if south is not None else 0.0
    high = (north - lat) * METERS_PER_DEGREE_LAT if north is not None else 0.0
    return both, low, high


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2:
        return None
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right)
    )
    return numerator / denominator if denominator else None
