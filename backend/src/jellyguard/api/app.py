from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from jellyguard.adapters.public_collectors import PublicCollectors
from jellyguard.composition import create_service
from jellyguard.config.settings import Settings, load_settings
from jellyguard.domain.services import SYNTHETIC_ENGINE_ID, DomainService
from jellyguard.mcp.server import create_mcp_server


class SearchRequest(BaseModel):
    site_id: str = "HANUL_PUBLIC_DEMO"
    bbox: dict[str, float] | None = None
    time_from: str | None = None
    time_to: str | None = None
    allowed_modes: list[str] = Field(default_factory=lambda: ["CACHED"])
    min_evidence_grade: str | None = None
    presence: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    cursor: str | None = None
    include_scenario_seeds: bool = False
    demo_current_cluster: bool = False


class ScenarioSeedRequest(BaseModel):
    geometry: dict[str, Any]
    reference_time: str
    author_note: str = ""
    basis: str = ""
    created_by: str = "unknown"


class RunRequest(BaseModel):
    seed_ids: list[str]
    field_ref: str | None = None
    horizons_h: list[int] = Field(default_factory=lambda: [3, 6, 12])
    scenario_id: str = "B2_current_only"
    gate_mapping: str = "DEMO_GATE"
    boundary_rule: str | None = None
    allowed_modes: list[str] = Field(default_factory=lambda: ["CACHED"])
    engine: str = SYNTHETIC_ENGINE_ID


class IntersectRequest(BaseModel):
    zone_ids: list[str]
    horizons_h: list[int] = Field(default_factory=lambda: [3, 6, 12])


def _is_external_tunnel_host(host: str) -> bool:
    host = host.split(":", 1)[0].lower()
    return host.endswith((".devtunnels.ms", ".devtunnels.com"))


def _supplied_mcp_key(request: Request) -> str | None:
    explicit = request.headers.get("x-mcp-client-key")
    if explicit:
        return explicit
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


def create_app(settings: Settings | None = None, service: DomainService | None = None) -> FastAPI:
    settings = settings or load_settings()
    service = service or create_service(settings)
    collectors = PublicCollectors(settings)
    mcp_server = create_mcp_server(service, collectors)
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_mcp_hosts(),
            allowed_origins=[],
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(
        title="JellyGuard",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_local_docs else None,
        redoc_url="/redoc" if settings.enable_local_docs else None,
        openapi_url="/openapi.json" if settings.enable_local_docs else None,
    )
    app.state.settings = settings
    app.state.service = service
    app.state.collectors = collectors
    app.state.mcp_server = mcp_server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dashboard_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "x-jellyguard-local-key"],
    )

    @app.middleware("http")
    async def protect_external_surface(request: Request, call_next):
        if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
            return await call_next(request)
        path = request.url.path.rstrip("/") or "/"
        host = request.headers.get("host", "")
        if _is_external_tunnel_host(host) and path != "/mcp":
            return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
        if path.startswith("/v1"):
            if not settings.local_rest_key:
                return JSONResponse({"error": "LOCAL_REST_AUTH_NOT_CONFIGURED"}, status_code=503)
            supplied_rest_key = request.headers.get("x-jellyguard-local-key")
            if supplied_rest_key is None or not hmac.compare_digest(
                supplied_rest_key.encode(), settings.local_rest_key.encode()
            ):
                return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        if path == "/mcp":
            if not settings.mcp_client_key:
                return JSONResponse({"error": "MCP_AUTH_NOT_CONFIGURED"}, status_code=503)
            supplied = _supplied_mcp_key(request)
            if supplied is None or not hmac.compare_digest(
                supplied.encode(), settings.mcp_client_key.encode()
            ):
                return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "profile": settings.profile,
            "source_mode": settings.source_mode,
            "live_enabled": bool(settings.enabled_live_sources()),
        }

    @app.get("/v1/sources/status")
    def get_source_status(
        site_id: str = "HANUL_PUBLIC_DEMO",
        allowed_modes: str = "CACHED,SYNTHETIC",
    ) -> dict:
        return service.get_source_status(
            site_id=site_id,
            allowed_modes=[mode.strip() for mode in allowed_modes.split(",") if mode.strip()],
            include_internal=True,
        ).model_dump(mode="json")

    @app.get("/v1/datasets")
    def list_datasets() -> dict:
        return {"datasets": collectors.list_datasets()}

    @app.get("/v1/datasets/{dataset_id}/status")
    def get_dataset_status(dataset_id: str) -> dict:
        try:
            return collectors.dataset_status(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="DATASET_NOT_FOUND") from exc

    @app.get("/v1/datasets/{dataset_id}/quality")
    def get_dataset_quality(dataset_id: str) -> dict:
        try:
            return collectors.dataset_quality(dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="DATASET_NOT_FOUND") from exc

    @app.get("/v1/dashboard/bootstrap")
    def dashboard_bootstrap(site_id: str = "HANUL_PUBLIC_DEMO") -> dict:
        return service.dashboard_bootstrap(site_id).model_dump(mode="json")

    @app.post("/v1/observations/search")
    def search_observations(request: SearchRequest) -> dict:
        return service.search_observations(
            site_id=request.site_id,
            bbox=request.bbox,
            time_from=request.time_from,
            time_to=request.time_to,
            allowed_modes=request.allowed_modes,
            min_evidence_grade=request.min_evidence_grade,
            presence=request.presence,
            limit=request.limit,
            cursor=request.cursor,
            include_scenario_seeds=request.include_scenario_seeds,
            demo_current_cluster=request.demo_current_cluster,
        ).model_dump(mode="json")

    @app.post("/v1/observations/scenario-seeds")
    def register_scenario_seed(request: ScenarioSeedRequest) -> dict:
        return service.register_scenario_seed(request.model_dump(mode="json"))

    @app.get("/v1/hanul/field-status")
    def get_field_status(
        site_id: str = "HANUL_PUBLIC_DEMO",
        as_of: str | None = None,
        horizons_h: str = "3,6,12",
        allowed_modes: str = "CACHED",
        include_context: bool = False,
    ) -> dict:
        return service.get_field_status(
            site_id=site_id,
            as_of=as_of,
            horizons_h=[int(value) for value in horizons_h.split(",") if value.strip()],
            allowed_modes=[mode.strip() for mode in allowed_modes.split(",") if mode.strip()],
            include_context=include_context,
        ).model_dump(mode="json")

    @app.post("/v1/hanul/runs")
    def run_transport(request: RunRequest) -> dict:
        return service.run_transport(
            seed_ids=request.seed_ids,
            field_ref=request.field_ref,
            horizons_h=request.horizons_h,
            scenario_id=request.scenario_id,
            gate_mapping=request.gate_mapping,
            boundary_rule=request.boundary_rule,
            allowed_modes=request.allowed_modes,
            engine=request.engine,
        ).model_dump(mode="json")

    @app.get("/v1/hanul/zones")
    def list_zones(
        site_id: str = "HANUL_PUBLIC_DEMO",
        access_class: str = "public",
        as_of: str | None = None,
    ) -> dict:
        return service.list_zones(
            site_id=site_id,
            access_class=access_class,
            as_of=as_of,
        ).model_dump(mode="json")

    @app.post("/v1/hanul/runs/{run_id}/intersect")
    def intersect_zone(run_id: str, request: IntersectRequest) -> dict:
        return service.intersect_zone(
            run_id=run_id,
            zone_ids=request.zone_ids,
            horizons_h=request.horizons_h,
        ).model_dump(mode="json")

    @app.get("/v1/hanul/runs/{run_id}/explain")
    def explain_run(run_id: str, include: str = "") -> dict:
        return service.explain_run(
            run_id=run_id,
            include=[value.strip() for value in include.split(",") if value.strip()],
        ).model_dump(mode="json")

    @app.get("/v1/hanul/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        return service.get_run(run_id).model_dump(mode="json")

    @app.get("/v1/hanul/explain")
    def explain(
        run_id: str | None = None,
        query_id: str | None = None,
        include: str = "",
    ) -> dict:
        return service.explain_run(
            run_id=run_id,
            query_id=query_id,
            include=[value.strip() for value in include.split(",") if value.strip()],
        ).model_dump(mode="json")

    if settings.dashboard_dist.is_dir():
        app.mount(
            "/dashboard",
            StaticFiles(directory=settings.dashboard_dist, html=True),
            name="dashboard",
        )

    app.mount("/", mcp_app)
    return app
