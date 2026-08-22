from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import CalculationStatus, ClaimType, DataMode, ErrorCode


class ServiceError(BaseModel):
    code: ErrorCode
    message: str
    unavailable_reason: str | None = None
    required: list[str] = Field(default_factory=list)


class ComponentStatus(BaseModel):
    source_id: str
    role: str
    status: CalculationStatus
    selected: bool = False
    source_data_mode: DataMode | None = None
    reason_codes: list[str] = Field(default_factory=list)


class RawPayload(BaseModel):
    source_id: str
    request_spec: dict[str, Any]
    redacted_endpoint: str
    http_status: int | None = None
    provider_result_code: str | None = None
    fetched_at: str | None = None
    issued_at: str | None = None
    valid_at: str | None = None
    content_checksum: str
    request_fingerprint: str
    fixture_checksum: str | None = None
    source_data_mode: DataMode
    adapter_version: str
    license: str
    rows_received: int
    rows_expected: int | None = None
    pages_received: int
    pages_expected: int | None = None
    partial: bool
    failed_pages: list[int] = Field(default_factory=list)


class DomainResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    schema_version: str = "1.0"
    tool_name: str
    tool_version: str = "0.1.0"
    as_of: str
    site_id: str = "HANUL_PUBLIC_DEMO"
    profile: str = "hanul_public_demo"
    status: CalculationStatus
    status_reasons: list[str] = Field(default_factory=list)
    component_status: list[ComponentStatus] = Field(default_factory=list)
    claim_type: ClaimType
    input_mode_set: list[DataMode] = Field(default_factory=list)
    effective_mode: str | None = None
    synthetic_dependency: bool = False
    replay_dependency: bool = False
    watermark_code: str | None = None
    selection_policy_version: str = "selection-v1"
    gate_policy_version: str = "gate-v1"
    selected_sources: list[dict[str, Any]] = Field(default_factory=list)
    excluded_sources: list[dict[str, Any]] = Field(default_factory=list)
    target_scope: str = "jellyfish"
    species_claim: str = "none"
    external_display_name: str = "한울 주변 대량 해파리 군집 감시"
    units: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: ServiceError | None = None
    provenance_ref: str
    deterministic_result_digest: str
    query_id: str | None = None
    run_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
