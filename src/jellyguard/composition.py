from datetime import UTC, datetime
from uuid import uuid4

from jellyguard.adapters.fixtures import (
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


def system_clock() -> datetime:
    return datetime.now(UTC)


def random_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def create_service(settings: Settings, clock=system_clock, new_id=random_id) -> DomainService:
    root = settings.blob_root
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
    return DomainService(
        settings,
        observation_records=HISTORICAL_OBSERVATIONS,
        catalog_records=JELLY_CATALOG_FIXTURE,
        point_context=HANUL_POINT_CONTEXT,
        synthetic_domain=SYNTHETIC_DOMAIN,
        demo_zones=DEMO_ZONES,
        source_manifests=source_manifests,
        seed_store=JsonlStore(root / "scenario-seeds.jsonl"),
        run_store=JsonlStore(root / "runs.jsonl"),
        provenance_store=JsonlStore(root / "provenance.jsonl"),
        audit_store=JsonlStore(root / "audit.jsonl"),
        clock=clock,
        new_id=new_id,
    )
