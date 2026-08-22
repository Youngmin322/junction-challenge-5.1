from __future__ import annotations

from mcp.server import MCPServer

from jellyguard.adapters.public_collectors import PublicCollectors
from jellyguard.contracts import DomainResult
from jellyguard.domain.services import SYNTHETIC_ENGINE_ID, DomainService


def create_mcp_server(
    service: DomainService,
    collectors: PublicCollectors | None = None,
) -> MCPServer:
    collectors = collectors or PublicCollectors(service.settings)
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
        scenario_id: str = "B2_current_only",
        gate_mapping: str = "DEMO_GATE",
        boundary_rule: str | None = None,
        allowed_modes: list[str] | None = None,
        engine: str = SYNTHETIC_ENGINE_ID,
    ) -> DomainResult:
        """등록 seed와 명시적 합성 field로 조건부 member 수송을 실행합니다.

        engine은 두 계산기 중 하나를 고릅니다.
        - `synthetic-rk4-v1`: 내장 RK4 수송. 해안선·수심을 보지 않습니다.
        - `risk-zone-connectivity-v1`: 조건부 연결영역 엔진. 중점법 수송에
          통과판정과 감시 게이트 선분교차를 더해 게이트 도달 member와 ETA
          분위수를 함께 반환합니다. Node 런타임이 필요하며, 사용할 수 없으면
          다른 엔진으로 대체하지 않고 ENGINE_UNAVAILABLE로 차단합니다.
        """

        return service.run_transport(
            seed_ids=seed_ids,
            field_ref=field_ref,
            horizons_h=horizons_h,
            scenario_id=scenario_id,
            gate_mapping=gate_mapping,
            boundary_rule=boundary_rule,
            allowed_modes=allowed_modes,
            engine=engine,
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
        """READY run과 공개 관측점 기반 감시격자의 member 교차를 계산합니다."""

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

    @server.tool()
    def get_ocean_current(
        date: str | None = None,
        hours: int = 24,
        tolerance_min: int = 60,
        include_series: bool = False,
        include_extra: bool = True,
    ) -> dict:
        """KHOA 부이·HF-RADAR 해류를 정시 슬롯 기준으로 통합합니다."""

        try:
            return collectors.get_ocean_current(
                date=date,
                hours=hours,
                tolerance_min=tolerance_min,
                include_series=include_series,
                include_extra=include_extra,
            )
        except (RuntimeError, SystemExit) as exc:
            return {"error": "KHOA_SERVICE_KEY_MISSING", "detail": str(exc)}

    @server.tool()
    def get_jellyfish_reports(
        sdate: str | None = None,
        edate: str | None = None,
        days: int = 30,
    ) -> dict:
        """NIFS 해파리 주간보고 목록을 조회합니다."""

        try:
            return collectors.get_jellyfish_reports(sdate=sdate, edate=edate, days=days)
        except (RuntimeError, SystemExit) as exc:
            return {"error": "NIFS_JELLY_KEY_MISSING", "detail": str(exc)}

    @server.tool()
    def get_marine_environment(
        sdate: str | None = None,
        edate: str | None = None,
        redtide_days: int = 30,
        soo_days: int = 365,
    ) -> dict:
        """NIFS 적조·정선해양관측 자료를 함께 조회합니다."""

        try:
            return collectors.get_marine_environment(
                sdate=sdate,
                edate=edate,
                redtide_days=redtide_days,
                soo_days=soo_days,
            )
        except (RuntimeError, SystemExit) as exc:
            return {"error": "NIFS_KEY_MISSING", "detail": str(exc)}

    return server
