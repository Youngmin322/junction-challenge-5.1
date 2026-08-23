import math

from jellyguard.domain.convention import (
    FROM,
    INCONCLUSIVE,
    TOWARD,
    verify_flow_direction_convention,
)

STEP_HOURS = 200
GRID = [(37.00 + 0.03 * i, 129.40 + 0.03 * j) for i in range(3) for j in range(3)]


def _rows(*, flip: bool, gradient_per_degree: float = 2.0, speed: float = 0.2):
    """Build a field where a known eastward flow advects a known west-east gradient.

    Temperature rises to the east, so an eastward flow must cool each cell over time.
    ``flip`` writes the direction under the opposite convention while keeping the
    temperature field identical, which is exactly the ambiguity the check must resolve.
    """
    rows = []
    for step in range(STEP_HOURS):
        hours = step
        for lat, lon in GRID:
            # East is warmer; the whole pattern drifts east, so each fixed cell cools.
            drift_degrees = speed * hours * 3600 / (111_320 * math.cos(math.radians(lat)))
            temperature = 20.0 + gradient_per_degree * ((lon - 129.40) - drift_degrees)
            bearing = 90.0 if not flip else 270.0
            rows.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "valid_at": f"2026-08-{22 + hours // 24:02d} {hours % 24:02d}:00:00",
                    "current_direction": bearing,
                    "current_speed": speed,
                    "water_temperature": temperature,
                }
            )
    return rows


def test_toward_convention_is_detected_from_temperature_advection():
    result = verify_flow_direction_convention(_rows(flip=False))
    assert result["verdict"] == TOWARD
    assert result["correlation_toward"] > 0
    assert result["sample_size"] >= result["minimum_sample_size"]
    assert result["provider_documented"] is False
    assert result["basis"] == "check_based_provider_unconfirmed"


def test_from_convention_is_detected_when_the_bearing_is_flipped():
    result = verify_flow_direction_convention(_rows(flip=True))
    assert result["verdict"] == FROM
    assert result["correlation_toward"] < 0


def test_too_few_samples_stay_inconclusive_instead_of_guessing():
    rows = _rows(flip=False)[:60]
    result = verify_flow_direction_convention(rows)
    assert result["verdict"] == INCONCLUSIVE
    assert result["basis"] == "none"


def test_uniform_temperature_field_cannot_decide_and_says_so():
    rows = _rows(flip=False, gradient_per_degree=0.0)
    result = verify_flow_direction_convention(rows)
    assert result["verdict"] == INCONCLUSIVE


def test_toward_verdict_is_corroborated_by_khoa_institutional_documents():
    result = verify_flow_direction_convention(_rows(flip=False))
    corroboration = result["institutional_corroboration"]
    assert corroboration["status"] == "corroborated"
    assert corroboration["institutional_convention"] == TOWARD
    assert len(corroboration["citations"]) == 2
    assert all("url" in c and "quote" in c for c in corroboration["citations"])


def test_from_verdict_conflicts_with_khoa_institutional_documents():
    result = verify_flow_direction_convention(_rows(flip=True))
    corroboration = result["institutional_corroboration"]
    assert corroboration["status"] == "conflicting"


def test_inconclusive_verdict_has_no_applicable_corroboration():
    rows = _rows(flip=False)[:60]
    result = verify_flow_direction_convention(rows)
    assert result["institutional_corroboration"]["status"] == "not_applicable"


def test_institutional_corroboration_never_flips_provider_documented():
    """Corroboration from KHOA's general documents is not this API's own spec sheet,
    so it must never be allowed to quietly upgrade provider_documented to True."""
    result = verify_flow_direction_convention(_rows(flip=False))
    assert result["institutional_corroboration"]["status"] == "corroborated"
    assert result["provider_documented"] is False
