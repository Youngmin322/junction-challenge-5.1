from __future__ import annotations

from mcp.server import MCPServer

from jellyguard.contracts import DomainResult
from jellyguard.domain.services import DomainService


def create_mcp_server(service: DomainService) -> MCPServer:
    server = MCPServer(
        name="Hanul Jellyfish Monitoring MCP",
        description="공개 해파리·해양자료와 프로토타입 감시격자의 근거·자료부족을 조회합니다.",
    )

    @server.tool()
    def search_observations(
        site_id: str = "HANUL_PUBLIC_DEMO",
        bbox: dict[str, float] | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        allowed_modes: list[str] | None = None,
        min_evidence_grade: str | None = None,
        presence: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        include_scenario_seeds: bool = False,
    ) -> DomainResult:
        """직접관측과 보고서 catalog를 분리해 검색합니다."""

        return service.search_observations(
            site_id=site_id,
            bbox=bbox,
            time_from=time_from,
            time_to=time_to,
            allowed_modes=allowed_modes,
            min_evidence_grade=min_evidence_grade,
            presence=presence,
            limit=limit,
            cursor=cursor,
            include_scenario_seeds=include_scenario_seeds,
        )

    @server.tool()
    def get_field_status(
        site_id: str = "HANUL_PUBLIC_DEMO",
        as_of: str | None = None,
        horizons_h: list[int] | None = None,
        allowed_modes: list[str] | None = None,
        include_context: bool = False,
    ) -> DomainResult:
        """한울 면 유동장 후보와 차단·coverage 상태를 조회합니다."""

        return service.get_field_status(
            site_id=site_id,
            as_of=as_of,
            horizons_h=horizons_h,
            allowed_modes=allowed_modes,
            include_context=include_context,
        )

    @server.tool()
    def run_transport(
        seed_ids: list[str],
        field_ref: str | None = None,
        horizons_h: list[int] | None = None,
        scenario_id: str = "P0_BLOCKED",
        gate_mapping: str = "DEMO_GATE",
        boundary_rule: str | None = None,
        allowed_modes: list[str] | None = None,
    ) -> DomainResult:
        """등록 seed의 조건부 수송을 요청합니다. P0에서는 BLOCKED를 반환합니다."""

        return service.run_transport(
            seed_ids=seed_ids,
            field_ref=field_ref,
            horizons_h=horizons_h,
            scenario_id=scenario_id,
            gate_mapping=gate_mapping,
            boundary_rule=boundary_rule,
            allowed_modes=allowed_modes,
        )

    @server.tool()
    def list_zones(
        site_id: str = "HANUL_PUBLIC_DEMO",
        access_class: str = "public",
        as_of: str | None = None,
    ) -> DomainResult:
        """실제 취수구가 아닌 공개 관측점 기반 프로토타입 감시격자를 조회합니다."""

        return service.list_zones(site_id=site_id, access_class=access_class, as_of=as_of)

    @server.tool()
    def intersect_zone(
        run_id: str,
        zone_ids: list[str],
        horizons_h: list[int] | None = None,
    ) -> DomainResult:
        """run과 감시격자 교차를 요청합니다. P0에서는 BLOCKED를 반환합니다."""

        return service.intersect_zone(
            run_id=run_id,
            zone_ids=zone_ids,
            horizons_h=horizons_h,
        )

    @server.tool()
    def explain_run(
        run_id: str | None = None,
        query_id: str | None = None,
        include: list[str] | None = None,
    ) -> DomainResult:
        """입력·선택·차단 사유와 재현 근거를 템플릿으로 설명합니다."""

        return service.explain_run(run_id=run_id, query_id=query_id, include=include)

    return server
