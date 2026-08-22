import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from jellyguard.api import create_app
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
