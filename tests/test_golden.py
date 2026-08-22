from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jellyguard.composition import create_service
from jellyguard.config.settings import Settings


def test_six_tool_offline_golden_digests(tmp_path):
    counter = 0

    def new_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-GOLDEN-{counter:04d}"

    service = create_service(
        Settings(_env_file=None, blob_root=tmp_path),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
        new_id=new_id,
    )
    results = {}
    results["search_observations"] = service.search_observations(
        allowed_modes=["CACHED", "SYNTHETIC"], include_scenario_seeds=True
    )
    results["get_field_status"] = service.get_field_status(allowed_modes=["SYNTHETIC"])
    field_ref = results["get_field_status"].data["selected_field_ref"]
    results["run_transport"] = service.run_transport(
        seed_ids=["SEED-HANUL-DEMO-001"],
        field_ref=field_ref,
        horizons_h=[3, 6, 12],
        scenario_id="B2_current_only",
        gate_mapping="DEMO_GATE",
        boundary_rule=None,
        allowed_modes=["SYNTHETIC"],
    )
    run_id = results["run_transport"].run_id
    results["list_zones"] = service.list_zones()
    results["intersect_zone"] = service.intersect_zone(
        run_id=run_id,
        zone_ids=["DEMO_GATE_NAGOK_v1"],
        horizons_h=[3, 6, 12],
    )
    results["explain_run"] = service.explain_run(run_id=run_id, include=[])

    golden_path = Path(__file__).parent / "golden/p2_digests.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    actual = {name: result.deterministic_result_digest for name, result in results.items()}
    assert actual == golden

    forbidden_keys = {
        "probability",
        "arrival_probability",
        "blockage_probability",
        "stop_probability",
        "risk_score",
        "percent",
        "eta",
        "eta_minutes",
    }

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()), set())
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    for result in results.values():
        payload = result.model_dump(mode="json")
        assert forbidden_keys.isdisjoint(keys(payload))
        assert len(result.model_dump_json().encode()) < 256 * 1024
