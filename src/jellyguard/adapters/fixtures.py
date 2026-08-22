from __future__ import annotations

import hashlib

HISTORICAL_OBSERVATIONS = [
    {
        "observation_id": "OBS-HANUL-HIST-001",
        "source_id": "historical_observation_fixture",
        "source_class": "observation",
        "claim_type": "direct_observation",
        "observed_at": "2019-07-11T00:00:00Z",
        "geometry": {"type": "Point", "coordinates": [129.405, 37.09]},
        "presence": "detected",
        "evidence_grade": "D1",
        "data_mode": "CACHED",
        "warnings": ["과거 출현보고 재생자료이며 현재 상태가 아닙니다."],
    }
]

JELLY_CATALOG_FIXTURE = [
    {
        "catalog_id": "NIFS-WEEKLY-FIXTURE-001",
        "title": "해파리 주간보고 fixture",
        "registered_at": "2026-08-20T00:00:00Z",
        "source_id": "nifs_jelly_catalog",
        "claim_type": "context/report_catalog",
    }
]

DEFAULT_SCENARIO_SEEDS = [
    {
        "seed_id": "SEED-HANUL-DEMO-001",
        "geometry": {"type": "Point", "coordinates": [129.46, 37.1]},
        "reference_time": "2026-08-23T00:00:00Z",
        "seed_mode": "synthetic",
        "author_note": "한울 공개 감시격자 P1 실행 확인용 합성 seed",
        "basis": "synthetic_demo_only",
        "created_by": "fixture",
    }
]

HANUL_POINT_CONTEXT = [
    {
        "station_code": "HB_0007",
        "station_name": "온양",
        "lat": 37.01944,
        "lon": 129.425,
        "capabilities": ["current_direction", "current_speed", "water_temperature"],
        "crdir_convention": "UNVERIFIED",
    },
    {
        "station_code": "HB_0008",
        "station_name": "덕천",
        "lat": 37.1,
        "lon": 129.40416,
        "capabilities": ["current_direction", "current_speed", "water_temperature", "wind"],
        "crdir_convention": "UNVERIFIED",
    },
    {
        "station_code": "HB_0009",
        "station_name": "나곡",
        "lat": 37.11916,
        "lon": 129.39583,
        "capabilities": ["current_direction", "current_speed", "water_temperature"],
        "crdir_convention": "UNVERIFIED",
    },
]

SYNTHETIC_DOMAIN = {
    "domain_id": "SYNTH_DOMAIN_HANUL_v1",
    "bbox": {"lat_min": 36.99, "lat_max": 37.14, "lon_min": 129.36, "lon_max": 129.48},
    "spacing_deg": 0.01,
    "boundary_rule": None,
    "land_mask_rule": "none_synthetic_domain",
    "physical_realism": "none",
}

DEMO_ZONES = [
    {
        "zone_id": "DEMO_GATE_ONYANG_v1",
        "station_code": "HB_0007",
        "lat": 37.01944,
        "lon": 129.425,
    },
    {
        "zone_id": "DEMO_GATE_DEOKCHEON_v1",
        "station_code": "HB_0008",
        "lat": 37.1,
        "lon": 129.40416,
    },
    {
        "zone_id": "DEMO_GATE_NAGOK_v1",
        "station_code": "HB_0009",
        "lat": 37.11916,
        "lon": 129.39583,
    },
]


def _zone_version(zone_id: str, neighbor_mode: str) -> str:
    version_input = "|".join(
        [
            "SYNTH_DOMAIN_HANUL_v1",
            f"public_observation_station_prototype:{zone_id}",
            ",".join(sorted(zone["station_code"] for zone in DEMO_ZONES)),
            f"neighbor_mode={neighbor_mode}",
            "zone_policy_version=v1",
        ]
    )
    return hashlib.blake2b(version_input.encode(), digest_size=8).hexdigest()


for zone in DEMO_ZONES:
    zone.update(
        {
            "domain_id": "SYNTH_DOMAIN_HANUL_v1",
            "facility_geometry": None,
            "zone_version": _zone_version(zone["zone_id"], "core"),
            "zone_version_by_mode": {
                mode: _zone_version(zone["zone_id"], mode) for mode in ("core", "edge4", "edge8")
            },
            "disclaimer_code": "NOT_INTAKE_STRUCTURE",
            "display_disclaimer": "공개 관측점 기반 프로토타입 감시격자입니다. 실제 취수구·안전계통 경계가 아닙니다.",
        }
    )
