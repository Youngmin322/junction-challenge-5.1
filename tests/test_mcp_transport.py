import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from jellyguard.api import create_app
from jellyguard.composition import create_service
from jellyguard.config.settings import Settings

EXPECTED_TOOLS = {
    "search_observations",
    "get_field_status",
    "run_transport",
    "list_zones",
    "intersect_zone",
    "explain_run",
}


@pytest.mark.asyncio
async def test_streamable_http_exposes_exactly_six_tools():
    app = create_app(Settings(_env_file=None, mcp_client_key="secret"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://localhost",
                headers={"x-mcp-client-key": "secret"},
            ) as client,
            streamable_http_client("http://localhost/mcp", http_client=client) as (
                read_stream,
                write_stream,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_mcp_call_preserves_blocked_contract():
    app = create_app(
        Settings(_env_file=None, mcp_client_key="secret", local_rest_key="local-secret")
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://localhost",
                headers={
                    "x-mcp-client-key": "secret",
                    "x-jellyguard-local-key": "local-secret",
                },
            ) as client,
            streamable_http_client("http://localhost/mcp", http_client=client) as (
                read_stream,
                write_stream,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool("get_field_status", {"allowed_modes": ["LIVE"]})
            assert result.is_error is False
            assert result.structured_content["status"] == "BLOCKED"
            assert result.structured_content["synthetic_dependency"] is False
            rest = await client.get("/v1/hanul/field-status", params={"allowed_modes": "LIVE"})
            assert rest.status_code == 200
            assert (
                rest.json()["deterministic_result_digest"]
                == result.structured_content["deterministic_result_digest"]
            )


@pytest.mark.asyncio
async def test_all_six_tools_match_rest_digests(tmp_path):
    settings = Settings(
        _env_file=None,
        mcp_client_key="secret",
        local_rest_key="local-secret",
        blob_root=tmp_path,
    )
    service = create_service(settings)
    app = create_app(settings, service)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://localhost",
                headers={
                    "x-mcp-client-key": "secret",
                    "x-jellyguard-local-key": "local-secret",
                },
            ) as client,
            streamable_http_client("http://localhost/mcp", http_client=client) as (
                read_stream,
                write_stream,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()

            search_args = {
                "allowed_modes": ["CACHED", "SYNTHETIC"],
                "include_scenario_seeds": True,
            }
            mcp_search = await session.call_tool("search_observations", search_args)
            rest_search = await client.post("/v1/observations/search", json=search_args)
            assert (
                rest_search.json()["deterministic_result_digest"]
                == mcp_search.structured_content["deterministic_result_digest"]
            )

            field_args = {"allowed_modes": ["SYNTHETIC"]}
            mcp_field = await session.call_tool("get_field_status", field_args)
            rest_field = await client.get(
                "/v1/hanul/field-status", params={"allowed_modes": "SYNTHETIC"}
            )
            assert (
                rest_field.json()["deterministic_result_digest"]
                == mcp_field.structured_content["deterministic_result_digest"]
            )
            selected_field = mcp_field.structured_content["data"]["selected_field_ref"]

            run_args = {
                "seed_ids": ["SEED-HANUL-DEMO-001"],
                "field_ref": selected_field,
                "horizons_h": [3, 6, 12],
                "scenario_id": "B2_current_only",
                "gate_mapping": "DEMO_GATE",
                "boundary_rule": None,
                "allowed_modes": ["SYNTHETIC"],
            }
            mcp_run = await session.call_tool("run_transport", run_args)
            rest_run = await client.post("/v1/hanul/runs", json=run_args)
            assert (
                rest_run.json()["deterministic_result_digest"]
                == mcp_run.structured_content["deterministic_result_digest"]
            )
            run_id = mcp_run.structured_content["run_id"]

            zone_args = {"site_id": "HANUL_PUBLIC_DEMO", "access_class": "public"}
            mcp_zones = await session.call_tool("list_zones", zone_args)
            rest_zones = await client.get("/v1/hanul/zones", params=zone_args)
            assert (
                rest_zones.json()["deterministic_result_digest"]
                == mcp_zones.structured_content["deterministic_result_digest"]
            )

            intersect_args = {
                "run_id": run_id,
                "zone_ids": ["DEMO_GATE_NAGOK_v1"],
                "horizons_h": [3, 6, 12],
            }
            mcp_intersection = await session.call_tool("intersect_zone", intersect_args)
            rest_intersection = await client.post(
                f"/v1/hanul/runs/{run_id}/intersect",
                json={
                    "zone_ids": intersect_args["zone_ids"],
                    "horizons_h": intersect_args["horizons_h"],
                },
            )
            assert (
                rest_intersection.json()["deterministic_result_digest"]
                == mcp_intersection.structured_content["deterministic_result_digest"]
            )

            explain_args = {"run_id": run_id, "include": []}
            mcp_explain = await session.call_tool("explain_run", explain_args)
            rest_explain = await client.get(f"/v1/hanul/runs/{run_id}/explain")
            assert (
                rest_explain.json()["deterministic_result_digest"]
                == mcp_explain.structured_content["deterministic_result_digest"]
            )
