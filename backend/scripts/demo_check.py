#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def require(result, *, status: str, watermark: str | None = None) -> dict:
    if result.is_error:
        raise AssertionError(str(result.content))
    payload = result.structured_content
    if payload["status"] != status:
        raise AssertionError(f"expected {status}, got {payload['status']}")
    if watermark is not None and payload["watermark_code"] != watermark:
        raise AssertionError("watermark mismatch")
    return payload


async def run_demo(url: str, client_key: str, engine: str) -> None:
    async with (
        httpx.AsyncClient(headers={"x-mcp-client-key": client_key}) as client,
        streamable_http_client(url, http_client=client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        expected = {
            "search_observations",
            "get_field_status",
            "run_transport",
            "list_zones",
            "intersect_zone",
            "explain_run",
            "get_ocean_current",
            "get_jellyfish_reports",
            "get_marine_environment",
        }
        if names != expected:
            raise AssertionError(f"tool surface changed: {sorted(names)}")

        search = require(
            await session.call_tool(
                "search_observations",
                {"allowed_modes": ["CACHED", "SYNTHETIC"], "include_scenario_seeds": True},
            ),
            status="READY",
        )
        print("1/6 search_observations", search["status"], search["watermark_code"])

        blocked = require(
            await session.call_tool("get_field_status", {"allowed_modes": ["CACHED"]}),
            status="BLOCKED",
        )
        print("2/6 get_field_status cached", blocked["status"], blocked["status_reasons"])

        field = require(
            await session.call_tool("get_field_status", {"allowed_modes": ["SYNTHETIC"]}),
            status="READY",
            watermark="SYNTHETIC_SCENARIO",
        )
        field_ref = field["data"]["selected_field_ref"]
        print("3/6 get_field_status synthetic", field["status"], field["watermark_code"])

        run = require(
            await session.call_tool(
                "run_transport",
                {
                    "seed_ids": ["SEED-HANUL-DEMO-001"],
                    "field_ref": field_ref,
                    "horizons_h": [3, 6, 12],
                    "scenario_id": "B2_current_only",
                    "allowed_modes": ["SYNTHETIC"],
                    "engine": engine,
                },
            ),
            status="READY",
            watermark="SYNTHETIC_SCENARIO",
        )
        run_id = run["run_id"]
        metric = run["data"]["computed_metric"]
        print("4/6 run_transport", run["status"], run_id, run["data"]["engine_version"])
        if engine == "risk-zone-connectivity-v1":
            # The connectivity engine adds gate-line crossings on top of the
            # cell intersection reported in step 5.
            for zone_id, gate in metric["gate_connectivity"].items():
                window = gate["first_crossing_window"] or gate["unavailable_reason"]
                print(
                    "    gate",
                    zone_id,
                    [item["display_string"] for item in gate["by_horizon"]],
                    window,
                )

        zones = require(await session.call_tool("list_zones", {}), status="READY")
        zone_ids = [zone["zone_id"] for zone in zones["data"]["zones"]]
        intersection = require(
            await session.call_tool(
                "intersect_zone",
                {"run_id": run_id, "zone_ids": zone_ids, "horizons_h": [3, 6, 12]},
            ),
            status="READY",
            watermark="SYNTHETIC_SCENARIO",
        )
        displays = [
            item["display_string"]
            for zone in intersection["data"]["zones"]
            for item in zone["sensitivity"]["edge8"]["by_horizon"]
        ]
        if not all(" of " in value for value in displays):
            raise AssertionError("member display contract changed")
        print("5/6 list_zones + intersect_zone", intersection["status"], displays)

        explanation = require(
            await session.call_tool("explain_run", {"run_id": run_id, "include": []}),
            status="READY",
        )
        if explanation["data"]["explanation"]["digest"] != run["deterministic_result_digest"]:
            raise AssertionError("explanation digest mismatch")
        print("6/6 explain_run", explanation["status"], "digest verified")


def main() -> int:
    parser = argparse.ArgumentParser(description="JellyGuard MCP six-tool demo check")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--client-key", default=os.getenv("JELLYGUARD_MCP_CLIENT_KEY"))
    parser.add_argument(
        "--engine",
        default="synthetic-rk4-v1",
        choices=["synthetic-rk4-v1", "risk-zone-connectivity-v1"],
        help="transport engine used by run_transport",
    )
    args = parser.parse_args()
    if not args.client_key:
        print("MCP client key is required", file=sys.stderr)
        return 2
    asyncio.run(run_demo(args.url, args.client_key, args.engine))
    print("DEMO CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
