from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from jellyguard.adapters.fixtures import (
    DEFAULT_SCENARIO_SEEDS,
    DEMO_ZONES,
    HANUL_POINT_CONTEXT,
    HISTORICAL_OBSERVATIONS,
    JELLY_CATALOG_FIXTURE,
    SYNTHETIC_DOMAIN,
)
from jellyguard.adapters.provenance import fixture_manifest
from jellyguard.adapters.stores import JsonlStore
from jellyguard.config.settings import Settings
from jellyguard.domain.services import DomainService
from jellyguard.domain.source_state import SourceResolver


def system_clock() -> datetime:
    return datetime.now(UTC)


def random_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def create_service(settings: Settings, clock=system_clock, new_id=random_id) -> DomainService:
    root = settings.blob_root
    seed_store = JsonlStore(root / "scenario-seeds.jsonl")
    for seed in DEFAULT_SCENARIO_SEEDS:
        if seed_store.get(seed["seed_id"]) is None:
            seed_store.put(seed["seed_id"], deepcopy(seed))
    source_manifests = {
        "historical_observation_fixture": fixture_manifest(
            source_id="historical_observation_fixture",
            payload=HISTORICAL_OBSERVATIONS,
            source_data_mode="CACHED",
            redacted_endpoint="fixture://historical-observations",
            rows_received=len(HISTORICAL_OBSERVATIONS),
        ),
        "nifs_jelly_catalog": fixture_manifest(
            source_id="nifs_jelly_catalog",
            payload=JELLY_CATALOG_FIXTURE,
            source_data_mode="CACHED",
            redacted_endpoint="fixture://nifs-jelly-catalog",
            rows_received=len(JELLY_CATALOG_FIXTURE),
        ),
        "khoa_tw_recent_hanul": fixture_manifest(
            source_id="khoa_tw_recent_hanul",
            payload=HANUL_POINT_CONTEXT,
            source_data_mode="CACHED",
            redacted_endpoint="fixture://khoa-tw-recent-hanul",
            rows_received=len(HANUL_POINT_CONTEXT),
        ),
        "synthetic_field": fixture_manifest(
            source_id="synthetic_field",
            payload=SYNTHETIC_DOMAIN,
            source_data_mode="SYNTHETIC",
            redacted_endpoint="synthetic://SYNTH_DOMAIN_HANUL_v1",
            rows_received=1,
        ),
        "khoa_roms_blocked_fixture": fixture_manifest(
            source_id="khoa_roms_blocked_fixture",
            payload={"error": "UPSTREAM_AUTH_FAILED"},
            source_data_mode="CACHED",
            redacted_endpoint="fixture://khoa-roms-auth-failure",
            rows_received=1,
            provider_result_code="UPSTREAM_AUTH_FAILED",
        ),
        "cached_field": fixture_manifest(
            source_id="cached_field",
            payload={"coverage": "NO_COVERAGE"},
            source_data_mode="CACHED",
            redacted_endpoint="fixture://cached-field-no-coverage",
            rows_received=1,
            provider_result_code="NO_COVERAGE",
        ),
    }
    fixture_payloads = {
        "historical_observation_fixture": {
            **source_manifests["historical_observation_fixture"],
            "payload": deepcopy(HISTORICAL_OBSERVATIONS),
        },
        "nifs_jelly_catalog": {
            **source_manifests["nifs_jelly_catalog"],
            "fetched_at": "2026-08-20T00:00:00Z",
            "payload": deepcopy(JELLY_CATALOG_FIXTURE),
        },
        "khoa_tw_recent_hanul": {
            **source_manifests["khoa_tw_recent_hanul"],
            "payload": deepcopy(HANUL_POINT_CONTEXT),
        },
        "synthetic_field": {
            **source_manifests["synthetic_field"],
            "payload": deepcopy(SYNTHETIC_DOMAIN),
        },
    }
    source_resolver = SourceResolver(settings, clock, fixture_payloads)
    return DomainService(
        settings,
        observation_records=deepcopy(HISTORICAL_OBSERVATIONS),
        catalog_records=deepcopy(JELLY_CATALOG_FIXTURE),
        point_context=deepcopy(HANUL_POINT_CONTEXT),
        synthetic_domain=deepcopy(SYNTHETIC_DOMAIN),
        demo_zones=deepcopy(DEMO_ZONES),
        source_manifests=source_manifests,
        seed_store=seed_store,
        run_store=JsonlStore(root / "runs.jsonl"),
        provenance_store=JsonlStore(root / "provenance.jsonl"),
        audit_store=JsonlStore(root / "audit.jsonl"),
        artifact_store=JsonlStore(root / "artifacts.jsonl"),
        source_resolver=source_resolver,
        clock=clock,
        new_id=new_id,
    )
