from __future__ import annotations

import math
from collections.abc import Callable
from copy import deepcopy
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
from .source_state import SourceResolver, SourceState
from .transport import (
    DomainGrid,
    deterministic_run_seed,
    parse_synthetic_field_ref,
    run_synthetic_transport,
)


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
        artifact_store: KeyValueStore,
        source_resolver: SourceResolver,
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
        self.artifact_store = artifact_store
        self.source_resolver = source_resolver
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

    @staticmethod
    def _resolved_source_entry(resolution, role: str) -> dict:
        manifest = dict(resolution.manifest or {})
        manifest.pop("payload", None)
        manifest.setdefault("source_id", resolution.source_id)
        manifest.setdefault("source_data_mode", resolution.data_mode)
        manifest.setdefault("license", resolution.license)
        manifest["role"] = role
        return manifest

    @staticmethod
    def _scenario_seed_source(seed: dict) -> dict:
        seed_id = seed["seed_id"]
        checksum = deterministic_digest(seed)
        return {
            "source_id": "scenario_seed_synthetic",
            "role": "required_input",
            "request_spec": {"seed_id": seed_id},
            "redacted_endpoint": "local://scenario-seeds",
            "http_status": None,
            "provider_result_code": "LOCAL_APPEND_ONLY",
            "fetched_at": None,
            "issued_at": None,
            "valid_at": seed.get("reference_time"),
            "content_checksum": checksum,
            "request_fingerprint": deterministic_digest({"seed_id": seed_id}),
            "fixture_checksum": checksum if seed.get("created_by") == "fixture" else None,
            "source_data_mode": "SYNTHETIC",
            "adapter_version": "scenario-seed-v1",
            "license": "user-or-demo-input",
            "rows_received": 1,
            "rows_expected": 1,
            "pages_received": 1,
            "pages_expected": 1,
            "partial": False,
            "failed_pages": [],
        }

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

    def get_source_status(
        self,
        *,
        site_id: str = "HANUL_PUBLIC_DEMO",
        allowed_modes: list[str] | None = None,
        include_internal: bool = False,
    ) -> DomainResult:
        modes = self._modes(allowed_modes)
        resolutions = self.source_resolver.resolve_all(modes)
        usable = {
            SourceState.LIVE_OK,
            SourceState.LIVE_STALE,
            SourceState.LIVE_UNKNOWN_AGE,
            SourceState.CACHED_FRESH,
            SourceState.CACHED_STALE,
            SourceState.CACHED_UNKNOWN_AGE,
            SourceState.CACHED_FIXTURE,
            SourceState.SYNTHETIC_EXPLICIT,
        }
        components = [
            ComponentStatus(
                source_id=item.source_id,
                role="optional_context" if item.optional else "candidate",
                status=(
                    CalculationStatus.STALE
                    if item.state in {SourceState.LIVE_STALE, SourceState.CACHED_STALE}
                    else (
                        CalculationStatus.DEGRADED
                        if item.state
                        in {SourceState.LIVE_UNKNOWN_AGE, SourceState.CACHED_UNKNOWN_AGE}
                        else (
                            CalculationStatus.READY
                            if item.state in usable
                            else CalculationStatus.BLOCKED
                        )
                    )
                ),
                selected=item.state in usable,
                source_data_mode=DataMode(item.data_mode) if item.data_mode else None,
                reason_codes=[item.public_reason_code] if item.public_reason_code else [],
                source_state=item.state.value if include_internal else item.public_reason_code,
            )
            for item in resolutions
        ]
        selected = [item for item in resolutions if item.state in usable]
        if any(
            item.state in {SourceState.CACHED_STALE, SourceState.LIVE_STALE} for item in selected
        ):
            status = CalculationStatus.STALE
        elif any(
            item.state in {SourceState.CACHED_UNKNOWN_AGE, SourceState.LIVE_UNKNOWN_AGE}
            for item in selected
        ) or any(item.optional and item.state not in usable for item in resolutions):
            status = CalculationStatus.DEGRADED
        else:
            status = CalculationStatus.READY
        return self._result(
            tool_name="get_source_status",
            status=status,
            claim_type=ClaimType.DIAGNOSTIC,
            data={
                "sources": [
                    item.public_dict(include_internal=include_internal) for item in resolutions
                ],
                "live_enabled": bool(self.settings.enabled_live_sources()),
                "profile": self.settings.profile,
                "source_mode": self.settings.source_mode if include_internal else None,
                "request_echo": {"site_id": site_id, "allowed_modes": [m.value for m in modes]},
            },
            component_status=components,
            modes=list(
                dict.fromkeys(DataMode(item.data_mode) for item in selected if item.data_mode)
            ),
            selected_sources=[
                self._resolved_source_entry(
                    item, "optional_context" if item.optional else "candidate"
                )
                for item in selected
            ],
            excluded_sources=[
                {
                    "source_id": item.source_id,
                    "reason_code": item.public_reason_code or item.state.value,
                }
                for item in resolutions
                if item.state not in usable
            ],
            warnings=[item.public_reason for item in resolutions if item.public_reason is not None],
            query_id=self.new_id("QUERY"),
        )

    def get_run(self, run_id: str) -> DomainResult:
        run = self.run_store.get(run_id)
        if run is not None:
            return DomainResult(**run)
        return self._result(
            tool_name="get_run",
            status=CalculationStatus.BLOCKED,
            claim_type=ClaimType.DIAGNOSTIC,
            data={"run_id": run_id},
            status_reasons=[ErrorCode.RUN_NOT_FOUND.value],
            error=ServiceError(code=ErrorCode.RUN_NOT_FOUND, message="run을 찾을 수 없습니다."),
            run_id=run_id,
        )

    def dashboard_bootstrap(self, site_id: str = "HANUL_PUBLIC_DEMO") -> DomainResult:
        source_status = self.get_source_status(
            site_id=site_id,
            allowed_modes=["CACHED", "SYNTHETIC"],
            include_internal=False,
        )
        return self._result(
            tool_name="dashboard_bootstrap",
            status=CalculationStatus(source_status.status),
            claim_type=ClaimType.DIAGNOSTIC,
            data={
                "site_id": site_id,
                "domain": self.synthetic_domain,
                "zones": self.demo_zones,
                "scenario_seeds": self.seed_store.values(),
                "sources": source_status.data["sources"],
                "source_status": source_status.status,
                "source_warnings": source_status.warnings,
                "horizons_h": [3, 6, 12],
                "profiles": ["B0_hold", "B2_current_only", "B3"],
                "dashboard_contract": "offline_public_watch_cells_v1",
            },
            modes=[DataMode.CACHED, DataMode.SYNTHETIC],
            warnings=[
                "합성 유동장에 의존한 조건부 시나리오입니다. 실제 예보가 아닙니다.",
                "합성 사각 도메인입니다. 해안선·육지·수심을 반영하지 않으며 입자가 육상 위를 지날 수 있습니다.",
                "공개 관측점 기반 프로토타입 감시격자입니다. 실제 취수구·안전계통 경계가 아닙니다.",
            ],
            query_id=self.new_id("QUERY"),
        )

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
        observation_resolution = self.source_resolver.resolve(
            "historical_observation_fixture", modes
        )
        catalog_resolution = self.source_resolver.resolve("nifs_jelly_catalog", modes)
        available_states = {
            SourceState.LIVE_OK,
            SourceState.LIVE_STALE,
            SourceState.LIVE_UNKNOWN_AGE,
            SourceState.CACHED_FRESH,
            SourceState.CACHED_STALE,
            SourceState.CACHED_UNKNOWN_AGE,
            SourceState.CACHED_FIXTURE,
        }
        candidates = (
            list(observation_resolution.payload or [])
            if observation_resolution.state in available_states
            else []
        )
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
        catalog = (
            list(catalog_resolution.payload or [])
            if catalog_resolution.state in available_states
            else []
        )
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
        resolved_available = [
            item
            for item in (observation_resolution, catalog_resolution)
            if item.state in available_states
        ]
        used_modes = list(
            dict.fromkeys(DataMode(item.data_mode) for item in resolved_available if item.data_mode)
        )
        if scenario_seeds:
            used_modes = list(dict.fromkeys([*used_modes, DataMode.SYNTHETIC]))
        return self._result(
            tool_name="search_observations",
            status=(
                CalculationStatus.STALE
                if any(
                    item.state in {SourceState.CACHED_STALE, SourceState.LIVE_STALE}
                    for item in resolved_available
                )
                else (
                    CalculationStatus.DEGRADED
                    if any(
                        item.state in {SourceState.CACHED_UNKNOWN_AGE, SourceState.LIVE_UNKNOWN_AGE}
                        for item in resolved_available
                    )
                    else CalculationStatus.READY
                )
            ),
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
                self._resolved_source_entry(
                    item,
                    "required_input"
                    if item.source_id == "historical_observation_fixture"
                    else "optional_context",
                )
                for item in resolved_available
            ],
            warnings=[
                "과거 녹화 자료 재생이며 현재 상태가 아닙니다.",
                *(
                    [catalog_resolution.public_reason]
                    if catalog_resolution.public_reason is not None
                    else []
                ),
            ],
            query_id=self.new_id("QUERY"),
        )

    @staticmethod
    def _roms_field_facts(grid_summary: dict | None, reason_code: str) -> dict:
        """Report what the ROMS response actually contained, including why it is unused.

        The field can be present and still be unusable for transport, so availability and
        usability are separate fields rather than one collapsed flag.
        """
        if not grid_summary:
            return {"available": False, "excluded_reason": reason_code}
        return {
            "available": True,
            "is_area_field": grid_summary.get("is_area_field", False),
            "cell_count": grid_summary.get("cell_count"),
            "lat_spacing_deg": grid_summary.get("lat_spacing_deg"),
            "lon_spacing_deg": grid_summary.get("lon_spacing_deg"),
            "covered_bbox": grid_summary.get("covered_bbox"),
            "timestep_count": grid_summary.get("timestep_count"),
            "valid_from_local": grid_summary.get("valid_from_local"),
            "valid_to_local": grid_summary.get("valid_to_local"),
            "issue_time_published": grid_summary.get("issue_time_published"),
            "depth_class": grid_summary.get("depth_class"),
            "crdir_convention": grid_summary.get("crdir_convention"),
            "usable_for_transport": False,
            "excluded_reason": reason_code,
        }

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
        point_resolution = self.source_resolver.resolve("khoa_tw_recent_hanul", modes)
        roms_resolution = self.source_resolver.resolve("khoa_roms_live", modes)
        point_context_available = point_resolution.state in {
            SourceState.LIVE_OK,
            SourceState.LIVE_STALE,
            SourceState.LIVE_UNKNOWN_AGE,
            SourceState.CACHED_FRESH,
            SourceState.CACHED_STALE,
            SourceState.CACHED_UNKNOWN_AGE,
            SourceState.CACHED_FIXTURE,
        }
        direction_warning = (
            "KHOA 관측점 유향 정의가 검증되지 않아 수송 계산에는 사용하지 않습니다."
            if point_context_available
            else None
        )
        # A ROMS response that actually arrived is a different fact from a ROMS response
        # that never came. Both stay out of the transport input, but for different reasons,
        # and collapsing them would hide that the area field is now in hand.
        roms_field_available = roms_resolution.state in {
            SourceState.LIVE_OK,
            SourceState.LIVE_STALE,
            SourceState.LIVE_UNKNOWN_AGE,
            SourceState.CACHED_FRESH,
            SourceState.CACHED_STALE,
            SourceState.CACHED_UNKNOWN_AGE,
        }
        roms_grid = (
            (roms_resolution.manifest or {}).get("grid_summary") if roms_field_available else None
        )
        roms_is_area_field = bool(roms_grid and roms_grid.get("is_area_field"))
        if roms_field_available and roms_is_area_field:
            # Coverage is satisfied; the blocker is now the unverified direction convention.
            roms_reason = ErrorCode.DIRECTION_UNVERIFIED.value
            roms_status = CalculationStatus.DEGRADED
        elif roms_field_available:
            # The provider answered but returned a single point, which is not a field.
            roms_reason = ErrorCode.NO_COVERAGE.value
            roms_status = CalculationStatus.BLOCKED
        else:
            roms_reason = roms_resolution.public_reason_code or "MODE_NOT_ALLOWED"
            roms_status = CalculationStatus.BLOCKED
        components = [
            ComponentStatus(
                source_id="khoa_roms_live",
                role="rejected_candidate",
                status=roms_status,
                source_data_mode=DataMode(roms_resolution.data_mode)
                if roms_field_available and roms_resolution.data_mode
                else None,
                reason_codes=[roms_reason],
                source_state=roms_resolution.state.value,
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
                source_data_mode=DataMode(point_resolution.data_mode)
                if point_context_available and point_resolution.data_mode
                else None,
                reason_codes=[]
                if point_context_available
                else [point_resolution.public_reason_code or "MODE_NOT_ALLOWED"],
                source_state=point_resolution.public_reason_code,
            ),
        ]
        selected: list[dict] = []
        excluded = [
            {"source_id": "khoa_roms_live", "reason_code": roms_reason},
            {"source_id": "khoa_hf_current_regression", "reason_code": ErrorCode.NO_COVERAGE.value},
            {
                "source_id": "khoa_roms_blocked_fixture",
                "reason_code": ErrorCode.UPSTREAM_AUTH_FAILED.value,
            },
            {"source_id": "cached_field", "reason_code": ErrorCode.NO_COVERAGE.value},
        ]
        if point_context_available:
            selected.append(self._resolved_source_entry(point_resolution, "optional_context"))
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
            synthetic_refs = {
                profile: (
                    f"synthetic:SYNTH_DOMAIN_HANUL_v1.{profile}:"
                    "2026-08-23T00:00:00Z:2026-08-23T00:00:00Z"
                )
                for profile in ("B0_hold", "B2_current_only", "B3")
            }
            return self._result(
                tool_name="get_field_status",
                status=CalculationStatus.READY,
                claim_type=ClaimType.DIAGNOSTIC,
                data={
                    "field_candidates": [
                        component.model_dump(mode="json") for component in components
                    ],
                    "selected_field_ref": synthetic_refs["B2_current_only"],
                    "synthetic_field_refs": synthetic_refs,
                    "roms_field": self._roms_field_facts(roms_grid, roms_reason),
                    "point_context": point_resolution.payload if point_context_available else [],
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
                warnings=[
                    "합성 유동장에 의존한 조건부 시나리오입니다. 실제 예보가 아닙니다.",
                    *([direction_warning] if direction_warning else []),
                    *(
                        [point_resolution.public_reason]
                        if point_resolution.public_reason is not None
                        else []
                    ),
                ],
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
                "roms_field": self._roms_field_facts(roms_grid, roms_reason),
                "point_context": point_resolution.payload if point_context_available else [],
                "context": [],
                "request_echo": {
                    "site_id": site_id,
                    "as_of": as_of,
                    "horizons_h": horizons_h or [3, 6, 12],
                    "include_context": include_context,
                },
                "context_mode_set": (
                    [point_resolution.data_mode]
                    if point_context_available and point_resolution.data_mode
                    else []
                ),
            },
            status_reasons=list(
                dict.fromkeys(
                    [ErrorCode.NO_COMPATIBLE_SOURCE.value, roms_reason, ErrorCode.NO_COVERAGE.value]
                )
            ),
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
            warnings=[direction_warning] if direction_warning else [],
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
        scenario_id: str = "B2_current_only",
        gate_mapping: str = "DEMO_GATE",
        boundary_rule: str | None = None,
        allowed_modes: list[str] | None = None,
    ) -> DomainResult:
        modes = self._modes(allowed_modes)
        run_id = self.new_id("RUN")
        requested_horizons = [3, 6, 12] if horizons_h is None else horizons_h
        seeds = [self.seed_store.get(seed_id) for seed_id in seed_ids]
        missing = [seed_id for seed_id, seed in zip(seed_ids, seeds, strict=True) if seed is None]
        error: ServiceError | None = None
        if boundary_rule is not None:
            error = ServiceError(
                code=ErrorCode.SCHEMA_INVALID,
                message="합성 도메인은 boundary_rule을 허용하지 않습니다.",
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
        elif len(set(seed_ids)) != len(seed_ids):
            error = ServiceError(
                code=ErrorCode.SCHEMA_INVALID,
                message="seed_ids에는 중복 ID를 넣을 수 없습니다.",
            )
        elif (
            not requested_horizons
            or len(requested_horizons) > 8
            or any(
                not isinstance(hour, int) or hour < 1 or hour > 24 for hour in requested_horizons
            )
        ):
            error = ServiceError(
                code=ErrorCode.SCHEMA_INVALID,
                message="horizons_h는 1~24 정수이며 최대 8개여야 합니다.",
            )
        elif gate_mapping != "DEMO_GATE":
            error = ServiceError(
                code=ErrorCode.GATE_MAPPING_BLOCKED,
                message="승인된 DEMO_GATE mapping만 사용할 수 있습니다.",
            )
        elif DataMode.SYNTHETIC not in modes:
            error = ServiceError(
                code=ErrorCode.MODEL_BLOCKED,
                message="합성 field 사용이 명시적으로 허용되지 않았습니다.",
                unavailable_reason="no_field",
                required=["allowed_modes에 SYNTHETIC 명시"],
            )
        elif field_ref is None:
            error = ServiceError(
                code=ErrorCode.MODEL_BLOCKED,
                message="선택된 field가 없습니다.",
                unavailable_reason="no_field",
                required=["get_field_status가 반환한 synthetic field_ref"],
            )
        grid = DomainGrid.from_fixture(self.synthetic_domain)
        valid_seeds = [seed for seed in seeds if seed is not None]
        if error is None:
            for seed in valid_seeds:
                geometry = seed.get("geometry", {})
                coordinates = geometry.get("coordinates")
                if (
                    geometry.get("type") != "Point"
                    or not isinstance(coordinates, list)
                    or len(coordinates) != 2
                    or any(
                        not isinstance(value, (int, float)) or not math.isfinite(value)
                        for value in coordinates
                    )
                ):
                    error = ServiceError(
                        code=ErrorCode.SCHEMA_INVALID,
                        message="P1 seed geometry는 유한한 WGS84 GeoJSON Point만 허용합니다.",
                    )
                    break
                if not grid.contains(coordinates[0], coordinates[1]):
                    error = ServiceError(
                        code=ErrorCode.MODEL_BLOCKED,
                        message="seed가 합성 도메인 범위 밖에 있습니다.",
                        unavailable_reason="outside_coverage",
                    )
                    break

        profile_id: str | None = None
        if error is None and field_ref is not None:
            if not field_ref.startswith("synthetic:"):
                if "khoa_tw_recent_hanul" in field_ref:
                    error = ServiceError(
                        code=ErrorCode.DIRECTION_UNVERIFIED,
                        message="점관측 유향 convention이 검증되지 않아 수송장으로 사용할 수 없습니다.",
                        unavailable_reason="direction_unverified",
                    )
                else:
                    error = ServiceError(
                        code=ErrorCode.NO_COMPATIBLE_SOURCE,
                        message="승인된 합성 grid와 호환되지 않는 field_ref입니다.",
                    )
            else:
                try:
                    profile_id = parse_synthetic_field_ref(field_ref, grid.domain_id)
                except LookupError as exc:
                    error = ServiceError(code=ErrorCode.NO_COMPATIBLE_SOURCE, message=str(exc))
                except ValueError as exc:
                    error = ServiceError(code=ErrorCode.SCHEMA_INVALID, message=str(exc))

        normalized_horizons = (
            sorted(set(requested_horizons))
            if all(isinstance(hour, int) for hour in requested_horizons)
            else list(requested_horizons)
        )
        request_echo = {
            "seed_ids": sorted(seed_ids),
            "field_ref": field_ref,
            "horizons_h": normalized_horizons,
            "scenario_id": scenario_id,
            "gate_mapping": gate_mapping,
            "boundary_rule": boundary_rule,
            "zone_versions": sorted(
                {
                    version
                    for zone in self.demo_zones
                    for version in zone["zone_version_by_mode"].values()
                }
            ),
        }
        if error is not None:
            result = self._result(
                tool_name="run_transport",
                status=CalculationStatus.BLOCKED,
                claim_type=ClaimType.CONDITIONAL_SCENARIO,
                data={**request_echo, "computed_metric": None},
                status_reasons=[error.code.value],
                modes=[],
                error=error,
                run_id=run_id,
            )
            self.run_store.put(run_id, result.model_dump(mode="json"))
            return result

        run_seed = deterministic_run_seed(
            {
                "seed_ids": tuple(sorted(seed_ids)),
                "field_ref": field_ref,
                "horizons_h": tuple(normalized_horizons),
                "scenario_id": scenario_id,
                "gate_mapping": gate_mapping,
                "engine_version": "synthetic-rk4-v1",
                "selection_policy_version": "selection-v1",
                "gate_policy_version": "gate-v1",
            }
        )
        computed, artifact = run_synthetic_transport(
            seeds=valid_seeds,
            grid=grid,
            profile_id=profile_id,
            horizons_h=normalized_horizons,
            run_seed=run_seed,
        )
        artifact["zones"] = deepcopy(self.demo_zones)
        artifact_id = f"ART-{run_seed:016x}"
        if self.artifact_store.get(artifact_id) is None:
            self.artifact_store.put(artifact_id, artifact)
        result = self._result(
            tool_name="run_transport",
            status=CalculationStatus.READY,
            claim_type=ClaimType.CONDITIONAL_SCENARIO,
            data={
                **request_echo,
                "computed_metric": computed,
                "artifact_refs": [f"jsonl://artifacts/{artifact_id}"],
                "engine_version": "synthetic-rk4-v1",
                "reproducibility": computed["reproducibility"],
                "disclaimer_code": "NOT_INTAKE_STRUCTURE",
            },
            modes=[DataMode.SYNTHETIC],
            selected_sources=[
                *(
                    self._scenario_seed_source(seed)
                    for seed in sorted(valid_seeds, key=lambda item: item["seed_id"])
                ),
                self._source_entry("synthetic_field", "required_input"),
            ],
            warnings=[
                "합성 유동장에 의존한 조건부 시나리오입니다. 실제 예보가 아닙니다.",
                "합성 사각 도메인입니다. 해안선·육지·수심을 반영하지 않으며 입자가 육상 위를 지날 수 있습니다.",
                "공개 관측점 기반 프로토타입 감시격자입니다. 실제 취수구·안전계통 경계가 아닙니다.",
            ],
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
        raw_horizons = [3, 6, 12] if horizons_h is None else horizons_h
        requested_horizons = sorted(set(raw_horizons))
        if (
            not requested_horizons
            or len(raw_horizons) > 8
            or any(
                not isinstance(hour, int) or hour < 1 or hour > 24 for hour in requested_horizons
            )
        ):
            error = ServiceError(
                code=ErrorCode.SCHEMA_INVALID,
                message="horizons_h는 1~24 정수이며 최대 8개여야 합니다.",
            )
        elif missing_zones:
            error = ServiceError(
                code=ErrorCode.ZONE_NOT_FOUND,
                message="감시격자를 찾을 수 없습니다.",
                required=[f"known zone_id: {', '.join(sorted(known_zone_ids))}"],
            )
        elif run is None:
            error = ServiceError(code=ErrorCode.RUN_NOT_FOUND, message="run을 찾을 수 없습니다.")
        elif run["status"] != CalculationStatus.READY.value:
            error = ServiceError(
                code=ErrorCode.MODEL_BLOCKED,
                message="BLOCKED run에는 감시격자 교차를 계산하지 않습니다.",
                unavailable_reason=run.get("error", {}).get(
                    "unavailable_reason", "domain_insufficient"
                ),
            )
        else:
            error = None
        if error is not None:
            return self._result(
                tool_name="intersect_zone",
                status=CalculationStatus.BLOCKED,
                claim_type=ClaimType.CONDITIONAL_SCENARIO,
                data={
                    "run_id": run_id,
                    "zone_ids": zone_ids,
                    "horizons_h": requested_horizons,
                    "members_intersected": None,
                    "members_total": None,
                    "display_string": None,
                    "first_intersection_window": None,
                },
                status_reasons=[error.code.value],
                error=error,
                run_id=run_id,
            )

        artifact_ref = run["data"]["artifact_refs"][0]
        artifact_id = artifact_ref.rsplit("/", 1)[-1]
        artifact = self.artifact_store.get(artifact_id)
        available_horizons = set(artifact["horizons_h"]) if artifact else set()
        if artifact is None or not set(requested_horizons) <= available_horizons:
            error = ServiceError(
                code=ErrorCode.SCHEMA_INVALID,
                message="요청 horizon이 run artifact에 존재하지 않습니다.",
            )
            return self._result(
                tool_name="intersect_zone",
                status=CalculationStatus.BLOCKED,
                claim_type=ClaimType.CONDITIONAL_SCENARIO,
                data={
                    "run_id": run_id,
                    "zone_ids": zone_ids,
                    "horizons_h": requested_horizons,
                    "computed_metric": None,
                },
                status_reasons=[error.code.value],
                error=error,
                run_id=run_id,
            )

        grid = DomainGrid.from_fixture(self.synthetic_domain)
        zones_by_id = {zone["zone_id"]: zone for zone in artifact["zones"]}
        zone_results = []
        for zone_id in zone_ids:
            zone = zones_by_id[zone_id]
            center_cell = grid.cell_id(zone["lon"], zone["lat"])
            sensitivity = {}
            for mode in ("core", "edge4", "edge8"):
                gate_cells = grid.neighbor_cells(center_cell, mode)
                by_horizon = []
                first_window = None
                previous_horizon = 0
                for hour in requested_horizons:
                    active_member_ids = {
                        item["member_index"] for item in artifact["snapshots"][str(hour)]
                    }
                    intersected = 0
                    for member in artifact["members"]:
                        if member["member_index"] not in active_member_ids:
                            continue
                        if any(
                            cell_id in gate_cells and first_minutes <= hour * 60
                            for cell_id, first_minutes in member["visited_cells"].items()
                        ):
                            intersected += 1
                    if intersected and first_window is None:
                        first_window = {
                            "from_h": previous_horizon,
                            "to_h": hour,
                            "basis": "requested_horizon_bracket",
                        }
                    by_horizon.append(
                        {
                            "horizon_h": hour,
                            "members_intersected": intersected,
                            "members_total": len(active_member_ids),
                            "display_string": f"{intersected} of {len(active_member_ids)}",
                            "terminated_by": run["data"]["computed_metric"]["horizon_summary"][
                                str(hour)
                            ]["terminated_by"],
                        }
                    )
                    previous_horizon = hour
                sensitivity[mode] = {
                    "by_horizon": by_horizon,
                    "first_intersection_window": first_window,
                    "unavailable_reason": None
                    if first_window is not None
                    else "no_intersection_within_horizons",
                }
            zone_results.append(
                {
                    "zone_id": zone_id,
                    "zone_version_by_mode": zone["zone_version_by_mode"],
                    "sensitivity": sensitivity,
                }
            )

        current_versions = {
            version for zone in self.demo_zones for version in zone["zone_version_by_mode"].values()
        }
        recorded_versions = set(run["data"]["zone_versions"])
        warnings = [
            "합성 유동장에 의존한 조건부 시나리오입니다. 실제 예보가 아닙니다.",
            "합성 사각 도메인입니다. 해안선·육지·수심을 반영하지 않으며 입자가 육상 위를 지날 수 있습니다.",
            "공개 관측점 기반 프로토타입 감시격자입니다. 실제 취수구·안전계통 경계가 아닙니다.",
        ]
        if recorded_versions != current_versions:
            warnings.append(
                f"{ErrorCode.ZONE_VERSION_MISMATCH.value}: "
                f"recorded={sorted(recorded_versions)}, current={sorted(current_versions)}"
            )
        return self._result(
            tool_name="intersect_zone",
            status=CalculationStatus.READY,
            claim_type=ClaimType.CONDITIONAL_SCENARIO,
            data={
                "run_id": run_id,
                "zone_ids": zone_ids,
                "horizons_h": requested_horizons,
                "zones": zone_results,
                "recorded_zone_versions": sorted(recorded_versions),
                "current_zone_versions": sorted(current_versions),
                "disclaimer_code": "NOT_INTAKE_STRUCTURE",
                "orchestrator": "mock",
            },
            modes=[DataMode.SYNTHETIC],
            selected_sources=[self._source_entry("synthetic_field", "required_input")],
            warnings=warnings,
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
            "assumptions": [
                "합성 사각 도메인과 선언된 속도 상수만 사용",
                "실제 해안선·수심·취수구 기하를 사용하지 않음",
            ],
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
