import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from jellyguard.composition import create_service
from jellyguard.config.settings import Settings


def test_p1_numeric_contract_is_unchanged():
    counter = 0

    def new_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-NUMERIC-{counter:04d}"

    current = create_service(
        Settings(_env_file=None, blob_root=Path(tempfile.mkdtemp())),
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
        new_id=new_id,
    )
    field = current.get_field_status(allowed_modes=["SYNTHETIC"])
    run = current.run_transport(
        seed_ids=["SEED-HANUL-DEMO-001"],
        field_ref=field.data["selected_field_ref"],
        horizons_h=[3, 6, 12],
        scenario_id="B2_current_only",
        gate_mapping="DEMO_GATE",
        boundary_rule=None,
        allowed_modes=["SYNTHETIC"],
    )
    intersection = current.intersect_zone(
        run_id=run.run_id,
        zone_ids=[zone["zone_id"] for zone in current.demo_zones],
        horizons_h=[3, 6, 12],
    )
    actual = {"horizons": {}, "zones": {}}
    for hour in (3, 6, 12):
        summary = run.data["computed_metric"]["horizon_summary"][str(hour)]
        envelope = run.data["computed_metric"]["envelopes"][str(hour)]
        bbox = envelope["bbox"]
        actual["horizons"][str(hour)] = {
            "released": summary["released"],
            "valid": summary["valid"],
            "terminated": sum(summary["terminated_by"].values()),
            "cells": len(envelope["occupied_cells"]),
            "bbox": [
                round(bbox["lon_min"], 9),
                round(bbox["lat_min"], 9),
                round(bbox["lon_max"], 9),
                round(bbox["lat_max"], 9),
            ],
        }
    for zone in intersection.data["zones"]:
        first = zone["sensitivity"]["edge8"]["first_intersection_window"]
        actual["zones"][zone["zone_id"]] = {
            mode: [item["members_intersected"] for item in zone["sensitivity"][mode]["by_horizon"]]
            for mode in ("core", "edge4", "edge8")
        }
        actual["zones"][zone["zone_id"]]["first"] = (
            [first["from_h"], first["to_h"]] if first else None
        )
    expected = json.loads(
        (Path(__file__).parent / "golden/p1_numeric.json").read_text(encoding="utf-8")
    )
    assert actual == expected
