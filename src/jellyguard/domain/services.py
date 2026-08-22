from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from jellyguard.config.settings import Settings
from jellyguard.contracts import (
    CalculationStatus,
    ClaimType,
    DataMode,
    DomainResult,
    ErrorCode,
    ServiceError,
)
from jellyguard.contracts.models import ComponentStatus

from .ports import KeyValueStore
from .provenance import deterministic_digest


class DomainService:
    """Application service shared by REST and MCP adapters."""

    def __init__(
        self,
        settings: Settings,
        *,
        observation_records: list[dict],
        catalog_records: list[dict],
        point_context: list[dict],
        synthetic_domain: dict,
        demo_zones: list[dict],
        source_manifests: dict[str, dict],
        seed_store: KeyValueStore,
        run_store: KeyValueStore,
        provenance_store: KeyValueStore,
        audit_store: KeyValueStore,
        clock: Callable[[], datetime],
        new_id: Callable[[str], str],
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.observation_records = observation_records
        self.catalog_records = catalog_records
        self.point_context = point_context
        self.synthetic_domain = synthetic_domain
        self.demo_zones = demo_zones
        self.source_manifests = source_manifests
        self.seed_store = seed_store
        self.run_store = run_store
        self.provenance_store = provenance_store
        self.audit_store = audit_store
        self.new_id = new_id

    def _result(
        self,
        *,
        tool_name: str,
        status: CalculationStatus,
        claim_type: ClaimType,
        data: dict,
        status_reasons: list[str] | None = None,
        component_status: list[ComponentStatus] | None = None,
        modes: list[DataMode] | None = None,
        selected_sources: list[dict] | None = None,
        excluded_sources: list[dict] | None = None,
        warnings: list[str] | None = None,
        error: ServiceError | None = None,
        query_id: str | None = None,
        run_id: str | None = None,
    ) -> DomainResult:
        modes = modes or []
        effective_mode = None
        if DataMode.SYNTHETIC in modes:
            effective_mode = "synthetic"
        elif DataMode.CACHED in modes:
            effective_mode = "cached"
        elif DataMode.LIVE in modes:
            effective_mode = "live"
        synthetic = DataMode.SYNTHETIC in modes
        replay = DataMode.CACHED in modes
        provenance_id = self.new_id("PROV")
        payload = {
            "schema_version": "1.0",
            "tool_name": tool_name,
            "tool_version": "0.1.0",
            "as_of": self.clock().isoformat().replace("+00:00", "Z"),
            "profile": self.settings.profile,
            "status": status,
            "status_reasons": status_reasons or [],
            "component_status": component_status or [],
            "claim_type": claim_type,
            "input_mode_set": modes,
            "effective_mode": effective_mode,
            "synthetic_dependency": synthetic,
            "replay_dependency": replay,
            "watermark_code": "SYNTHETIC_SCENARIO"
            if synthetic
            else ("CACHED_REPLAY" if replay else None),
            "selected_sources": selected_sources or [],
            "excluded_sources": excluded_sources or [],
            "warnings": warnings or [],
            "error": error,
            "provenance_ref": f"jsonl://provenance/{provenance_id}",
            "deterministic_result_digest": "",
            "query_id": query_id,
            "run_id": run_id,
            "data": data,
        }
        serialized = DomainResult(**payload).model_dump(mode="json")
        payload["deterministic_result_digest"] = deterministic_digest(serialized)
        self.provenance_store.put(
            provenance_id,
            {
                "tool_name": tool_name,
                "status": status.value,
                "status_reasons": status_reasons or [],
                "selected_sources": selected_sources or [],
                "excluded_sources": excluded_sources or [],
                "input_mode_set": [mode.value for mode in modes],
                "deterministic_result_digest": payload["deterministic_result_digest"],
            },
        )
        audit_id = self.new_id("AUDIT")
        self.audit_store.put(
            audit_id,
            {
                "ts": payload["as_of"],
                "tool": tool_name,
                "selected_source_ids": [item.get("source_id") for item in (selected_sources or [])],
                "excluded": excluded_sources or [],
                "status": status.value,
                "error_code": error.code.value if error else None,
                "run_id": run_id,
                "query_id": query_id,
                "digest": payload["deterministic_result_digest"],
            },
        )
        return DomainResult(**payload)

    @staticmethod
    def _modes(values: list[str] | None) -> list[DataMode]:
        values = values or [DataMode.CACHED.value]
        return list(dict.fromkeys(DataMode(value) for value in values))

    def _source_entry(self, source_id: str, role: str) -> dict:
        return {**self.source_manifests[source_id], "role": role}

    def register_scenario_seed(self, payload: dict) -> dict:
        seed_id = self.new_id("SEED")
        record = {
            "seed_id": seed_id,
            "geometry": payload["geometry"],
            "reference_time": payload["reference_time"],
            "seed_mode": "synthetic",
            "author_note": payload.get("author_note", ""),
            "basis": payload.get("basis", ""),
            "created_by": payload.get("created_by", "unknown"),
        }
        self.seed_store.put(seed_id, record)
        return record

    def search_observations(
        self,
        *,
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
        modes = self._modes(allowed_modes)
        candidates = list(self.observation_records) if DataMode.CACHED in modes else []
        records = list(candidates)
        excluded_counts: dict[str, int] = {}
        request_echo = {
            "site_id": site_id,
            "bbox": bbox,
            "time_from": time_from,
            "time_to": time_to,
            "min_evidence_grade": min_evidence_grade,
            "presence": presence,
            "limit": limit,
            "cursor": cursor,
        }

        try:
            if limit < 1:
                raise ValueError("limit must be positive")
            offset = int(cursor or 0)
            if offset < 0:
                raise ValueError("cursor must be non-negative")
            if min_evidence_grade is not None and (
                len(min_evidence_grade) != 2
                or not min_evidence_grade.startswith("D")
                or not min_evidence_grade[1].isdigit()
                or not 0 <= int(min_evidence_grade[1]) <= 5
            ):
                raise ValueError("min_evidence_grade must be D0..D5")
            if bbox is not None:
                required_bbox = {"lon_min", "lon_max", "lat_min", "lat_max"}
                if not required_bbox <= bbox.keys():
                    raise ValueError("bbox requires lon_min/lon_max/lat_min/lat_max")
                if bbox["lon_min"] > bbox["lon_max"] or bbox["lat_min"] > bbox["lat_max"]:
                    raise ValueError("bbox minimum must not exceed maximum")
        except (TypeError, ValueError) as exc:
            return self._result(
                tool_name="search_observations",
                status=CalculationStatus.BLOCKED,
                claim_type=ClaimType.DIRECT_OBSERVATION,
                data={
                    "records": [],
                    "catalog_context": {"items": []},
                    "scenario_seeds": [],
                    "request_echo": request_echo,
                    "returned": 0,
                    "candidates_scanned": 0,
                    "excluded_counts": {},
                    "scenario_seeds_returned": 0,
                },
                status_reasons=[ErrorCode.SCHEMA_INVALID.value],
                error=ServiceError(code=ErrorCode.SCHEMA_INVALID, message=str(exc)),
                query_id=self.new_id("QUERY"),
            )

        def apply_filter(reason: str, predicate: Callable[[dict], bool]) -> None:
            nonlocal records
            before = len(records)
            records = [record for record in records if predicate(record)]
            if before != len(records):
                excluded_counts[reason] = before - len(records)

        if presence:
            apply_filter("presence", lambda record: record.get("presence") == presence)
        if time_from:
            apply_filter("time_from", lambda record: record.get("observed_at", "") >= time_from)
        if time_to:
            apply_filter("time_to", lambda record: record.get("observed_at", "") <= time_to)
        if min_evidence_grade:
            minimum = int(min_evidence_grade[1])

            def meets_grade(record: dict) -> bool:
                grade = record.get("evidence_grade")
                return (
                    isinstance(grade, str)
                    and len(grade) == 2
                    and grade.startswith("D")
                    and grade[1].isdigit()
                    and int(grade[1]) >= minimum
                )

            apply_filter(
                "min_evidence_grade",
                meets_grade,
            )
        if bbox:

            def inside_bbox(record: dict) -> bool:
                coordinates = record.get("geometry", {}).get("coordinates")
                return (
                    isinstance(coordinates, list)
                    and len(coordinates) >= 2
                    and bbox["lon_min"] <= coordinates[0] <= bbox["lon_max"]
                    and bbox["lat_min"] <= coordinates[1] <= bbox["lat_max"]
                )

            apply_filter(
                "bbox",
                inside_bbox,
            )
        if offset:
            excluded_counts["cursor_offset"] = min(offset, len(records))
            records = records[offset:]
        if len(records) > limit:
            excluded_counts["limit"] = len(records) - limit
            records = records[:limit]
        catalog = self.catalog_records if DataMode.CACHED in modes else []
        scenario_seeds = (
            self.seed_store.values()
            if include_scenario_seeds and DataMode.SYNTHETIC in modes
            else []
        )
        if not records and not catalog:
            return self._result(
                tool_name="search_observations",
                status=CalculationStatus.BLOCKED,
                claim_type=ClaimType.DIRECT_OBSERVATION,
                data={
                    "records": [],
                    "catalog_context": {"items": []},
                    "scenario_seeds": scenario_seeds,
                    "request_echo": request_echo,
                    "returned": 0,
                    "candidates_scanned": 0,
                    "excluded_counts": {},
                    "scenario_seeds_returned": len(scenario_seeds),
                },
                status_reasons=[ErrorCode.NO_COMPATIBLE_SOURCE.value],
                modes=[DataMode.SYNTHETIC] if scenario_seeds else [],
                error=ServiceError(
                    code=ErrorCode.NO_COMPATIBLE_SOURCE,
                    message="허용된 모드에서 관측·catalog 자료를 선택할 수 없습니다.",
                ),
                query_id=self.new_id("QUERY"),
            )
        used_modes = [DataMode.CACHED]
        if scenario_seeds:
            used_modes.append(DataMode.SYNTHETIC)
        return self._result(
            tool_name="search_observations",
            status=CalculationStatus.READY,
            claim_type=ClaimType.DIRECT_OBSERVATION,
            data={
                "records": records,
                "catalog_context": {"items": catalog},
                "scenario_seeds": scenario_seeds,
                "request_echo": request_echo,
                "returned": len(records),
                "candidates_scanned": len(candidates),
                "excluded_counts": excluded_counts,
                "scenario_seeds_returned": len(scenario_seeds),
            },
            modes=used_modes,
            selected_sources=[
                self._source_entry("historical_observation_fixture", "required_input"),
                self._source_entry("nifs_jelly_catalog", "optional_context"),
            ],
            warnings=["과거 녹화 자료 재생이며 현재 상태가 아닙니다."],
            query_id=self.new_id("QUERY"),
        )

    def get_field_status(
        self,
        *,
        site_id: str = "HANUL_PUBLIC_DEMO",
        as_of: str | None = None,
        horizons_h: list[int] | None = None,
        allowed_modes: list[str] | None = None,
        include_context: bool = False,
    ) -> DomainResult:
        modes = self._modes(allowed_modes)
        synthetic_allowed = DataMode.SYNTHETIC in modes
        point_context_available = DataMode.CACHED in modes
        components = [
            ComponentStatus(
                source_id="khoa_roms_live",
                role="rejected_candidate",
                status=CalculationStatus.BLOCKED,
                reason_codes=[ErrorCode.UPSTREAM_AUTH_FAILED.value],
            ),
            ComponentStatus(
                source_id="khoa_hf_current_regression",
                role="rejected_candidate",
                status=CalculationStatus.BLOCKED,
                reason_codes=[ErrorCode.NO_COVERAGE.value],
            ),
            ComponentStatus(
                source_id="khoa_roms_blocked_fixture",
                role="rejected_candidate",
                status=CalculationStatus.BLOCKED,
                source_data_mode=DataMode.CACHED,
                reason_codes=[ErrorCode.UPSTREAM_AUTH_FAILED.value],
            ),
            ComponentStatus(
                source_id="cached_field",
                role="rejected_candidate",
                status=CalculationStatus.BLOCKED,
                source_data_mode=DataMode.CACHED,
                reason_codes=[ErrorCode.NO_COVERAGE.value],
            ),
            ComponentStatus(
                source_id="khoa_tw_recent_hanul",
                role="optional_context",
                status=CalculationStatus.READY
                if point_context_available
                else CalculationStatus.BLOCKED,
                source_data_mode=DataMode.CACHED if point_context_available else None,
                reason_codes=[] if point_context_available else ["MODE_NOT_ALLOWED"],
            ),
        ]
        selected: list[dict] = []
        excluded = [
            {"source_id": "khoa_roms_live", "reason_code": ErrorCode.UPSTREAM_AUTH_FAILED.value},
            {"source_id": "khoa_hf_current_regression", "reason_code": ErrorCode.NO_COVERAGE.value},
            {
                "source_id": "khoa_roms_blocked_fixture",
                "reason_code": ErrorCode.UPSTREAM_AUTH_FAILED.value,
            },
            {"source_id": "cached_field", "reason_code": ErrorCode.NO_COVERAGE.value},
        ]
        if point_context_available:
            selected.append(self._source_entry("khoa_tw_recent_hanul", "optional_context"))
        if synthetic_allowed:
            components.append(
                ComponentStatus(
                    source_id="synthetic_field",
                    role="required_input",
                    status=CalculationStatus.READY,
                    selected=True,
                    source_data_mode=DataMode.SYNTHETIC,
                )
            )
            selected.append(self._source_entry("synthetic_field", "required_input"))
            return self._result(
                tool_name="get_field_status",
                status=CalculationStatus.READY,
                claim_type=ClaimType.DIAGNOSTIC,
                data={
                    "field_candidates": [
                        component.model_dump(mode="json") for component in components
                    ],
                    "selected_field_ref": "synthetic:SYNTH_DOMAIN_HANUL_v1:p0",
                    "point_context": self.point_context if point_context_available else [],
                    "context": [] if not include_context else [{"context_ui_enabled": False}],
                    "request_echo": {
                        "site_id": site_id,
                        "as_of": as_of,
                        "horizons_h": horizons_h or [3, 6, 12],
                        "include_context": include_context,
                    },
                },
                component_status=components,
                modes=[DataMode.SYNTHETIC],
                selected_sources=selected,
                excluded_sources=excluded,
                warnings=["합성 유동장에 의존한 조건부 시나리오입니다. 실제 예보가 아닙니다."],
                query_id=self.new_id("QUERY"),
            )
        components.append(
            ComponentStatus(
                source_id="synthetic_field",
                role="rejected_candidate",
                status=CalculationStatus.BLOCKED,
                reason_codes=["MODE_NOT_ALLOWED"],
            )
        )
        return self._result(
            tool_name="get_field_status",
            status=CalculationStatus.BLOCKED,
            claim_type=ClaimType.DIAGNOSTIC,
            data={
                "field_candidates": [component.model_dump(mode="json") for component in components],
                "selected_field_ref": None,
                "point_context": self.point_context if point_context_available else [],
                "context": [],
                "request_echo": {
                    "site_id": site_id,
                    "as_of": as_of,
                    "horizons_h": horizons_h or [3, 6, 12],
                    "include_context": include_context,
                },
            },
            status_reasons=[
                ErrorCode.NO_COMPATIBLE_SOURCE.value,
                ErrorCode.UPSTREAM_AUTH_FAILED.value,
                ErrorCode.NO_COVERAGE.value,
            ],
            component_status=components,
            modes=[],
            selected_sources=selected,
            excluded_sources=excluded
            + [{"source_id": "synthetic_field", "reason_code": "MODE_NOT_ALLOWED"}],
            error=ServiceError(
                code=ErrorCode.NO_COMPATIBLE_SOURCE,
                message="한울을 포함하는 사용 가능한 면 유동장이 없습니다.",
                required=[
                    "한울 coverage와 방향 정의가 검증된 면 유동장 또는 명시적으로 허용된 합성 field"
                ],
            ),
            query_id=self.new_id("QUERY"),
        )

    def list_zones(
        self,
        *,
        site_id: str = "HANUL_PUBLIC_DEMO",
        access_class: str = "public",
        as_of: str | None = None,
    ) -> DomainResult:
        return self._result(
            tool_name="list_zones",
            status=CalculationStatus.READY,
            claim_type=ClaimType.DIAGNOSTIC,
            data={
                "domain": self.synthetic_domain,
                "zones": self.demo_zones,
                "request_echo": {
                    "site_id": site_id,
                    "access_class": access_class,
                    "as_of": as_of,
                },
            },
            modes=[DataMode.SYNTHETIC],
            selected_sources=[],
            warnings=[
                "합성 사각 도메인입니다. 해안선·육지·수심을 반영하지 않으며 입자가 육상 위를 지날 수 있습니다."
            ],
            query_id=self.new_id("QUERY"),
        )

    def run_transport(
        self,
        *,
        seed_ids: list[str],
        field_ref: str | None,
        horizons_h: list[int] | None = None,
        scenario_id: str = "P0_BLOCKED",
        gate_mapping: str = "DEMO_GATE",
        boundary_rule: str | None = None,
        allowed_modes: list[str] | None = None,
    ) -> DomainResult:
        modes = self._modes(allowed_modes)
        run_id = self.new_id("RUN")
        missing = [seed_id for seed_id in seed_ids if self.seed_store.get(seed_id) is None]
        if boundary_rule is not None:
            error = ServiceError(
                code=ErrorCode.SCHEMA_INVALID,
                message="P0 합성 도메인은 boundary_rule을 허용하지 않습니다.",
                unavailable_reason="unsupported_boundary_rule",
                required=["boundary_rule=null"],
            )
        elif missing or not seed_ids:
            error = ServiceError(
                code=ErrorCode.NO_OBSERVATION,
                message="유효한 seed가 없습니다.",
                unavailable_reason="no_seed",
                required=["등록된 scenario seed"],
            )
        else:
            error = ServiceError(
                code=ErrorCode.MODEL_BLOCKED,
                message="P0에서는 수송 계산을 수행하지 않습니다.",
                unavailable_reason="domain_insufficient",
                required=["P1 결정론적 수송 엔진 승인"],
            )
        result = self._result(
            tool_name="run_transport",
            status=CalculationStatus.BLOCKED,
            claim_type=ClaimType.CONDITIONAL_SCENARIO,
            data={
                "seed_ids": seed_ids,
                "field_ref": field_ref,
                "horizons_h": horizons_h or [3, 6, 12],
                "scenario_id": scenario_id,
                "gate_mapping": gate_mapping,
                "boundary_rule": boundary_rule,
                "zone_versions": sorted({zone["zone_version"] for zone in self.demo_zones}),
                "computed_metric": None,
            },
            status_reasons=[error.code.value],
            modes=[mode for mode in modes if mode in (DataMode.CACHED, DataMode.SYNTHETIC)],
            error=error,
            run_id=run_id,
        )
        self.run_store.put(run_id, result.model_dump(mode="json"))
        return result

    def intersect_zone(
        self,
        *,
        run_id: str,
        zone_ids: list[str],
        horizons_h: list[int] | None = None,
    ) -> DomainResult:
        run = self.run_store.get(run_id)
        known_zone_ids = {zone["zone_id"] for zone in self.demo_zones}
        missing_zones = [zone_id for zone_id in zone_ids if zone_id not in known_zone_ids]
        if missing_zones:
            error = ServiceError(
                code=ErrorCode.ZONE_NOT_FOUND,
                message="감시격자를 찾을 수 없습니다.",
                required=[f"known zone_id: {', '.join(sorted(known_zone_ids))}"],
            )
        elif run is None:
            error = ServiceError(code=ErrorCode.RUN_NOT_FOUND, message="run을 찾을 수 없습니다.")
        else:
            error = ServiceError(
                code=ErrorCode.MODEL_BLOCKED,
                message="P0에서는 감시격자 교차를 계산하지 않습니다.",
                unavailable_reason="domain_insufficient",
                required=["P1 교차 엔진 승인"],
            )
        return self._result(
            tool_name="intersect_zone",
            status=CalculationStatus.BLOCKED,
            claim_type=ClaimType.CONDITIONAL_SCENARIO,
            data={
                "run_id": run_id,
                "zone_ids": zone_ids,
                "horizons_h": horizons_h or [3, 6, 12],
                "members_intersected": None,
                "members_total": None,
                "display_string": None,
                "first_intersection_window": None,
            },
            status_reasons=[error.code.value],
            error=error,
            run_id=run_id,
        )

    def explain_run(
        self,
        *,
        run_id: str | None = None,
        query_id: str | None = None,
        include: list[str] | None = None,
    ) -> DomainResult:
        if (run_id is None) == (query_id is None):
            return self._result(
                tool_name="explain_run",
                status=CalculationStatus.BLOCKED,
                claim_type=ClaimType.DIAGNOSTIC,
                data={"run_id": run_id, "query_id": query_id, "explanation": None},
                status_reasons=[ErrorCode.SCHEMA_INVALID.value],
                error=ServiceError(
                    code=ErrorCode.SCHEMA_INVALID,
                    message="run_id 또는 query_id 중 하나만 지정해야 합니다.",
                ),
                run_id=run_id,
                query_id=query_id,
            )
        if query_id is not None:
            audit = next(
                (item for item in self.audit_store.values() if item.get("query_id") == query_id),
                None,
            )
            if audit is None:
                return self._result(
                    tool_name="explain_run",
                    status=CalculationStatus.BLOCKED,
                    claim_type=ClaimType.DIAGNOSTIC,
                    data={"run_id": None, "query_id": query_id, "explanation": None},
                    status_reasons=[ErrorCode.RUN_NOT_FOUND.value],
                    error=ServiceError(
                        code=ErrorCode.RUN_NOT_FOUND,
                        message="query를 찾을 수 없습니다.",
                    ),
                    query_id=query_id,
                )
            return self._result(
                tool_name="explain_run",
                status=CalculationStatus.READY,
                claim_type=ClaimType.DIAGNOSTIC,
                data={
                    "run_id": None,
                    "query_id": query_id,
                    "include": include or [],
                    "explanation": audit,
                },
                query_id=query_id,
            )

        run = self.run_store.get(run_id)
        if run is None:
            return self._result(
                tool_name="explain_run",
                status=CalculationStatus.BLOCKED,
                claim_type=ClaimType.DIAGNOSTIC,
                data={"run_id": run_id, "query_id": None, "explanation": None},
                status_reasons=[ErrorCode.RUN_NOT_FOUND.value],
                error=ServiceError(code=ErrorCode.RUN_NOT_FOUND, message="run을 찾을 수 없습니다."),
                run_id=run_id,
            )
        explanation = {
            "inputs": run["data"],
            "status": run["status"],
            "status_reasons": run["status_reasons"],
            "assumptions": ["P0에서는 수송·교차 계산을 수행하지 않음"],
            "digest": run["deterministic_result_digest"],
        }
        return self._result(
            tool_name="explain_run",
            status=CalculationStatus.READY,
            claim_type=ClaimType.DIAGNOSTIC,
            data={
                "run_id": run_id,
                "query_id": None,
                "include": include or [],
                "explanation": explanation,
            },
            run_id=run_id,
        )
