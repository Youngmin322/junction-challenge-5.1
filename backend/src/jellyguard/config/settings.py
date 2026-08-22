import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JELLYGUARD_",
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nifs_jelly_key: str | None = None
    nifs_redtide_key: str | None = None
    nifs_soo_key: str | None = None
    khoa_key: str | None = None
    mcp_client_key: str | None = None
    local_rest_key: str | None = None
    mcp_allowed_hosts: str = "localhost,localhost:*,127.0.0.1,127.0.0.1:*"
    profile: str = "hanul_public_demo"
    source_mode: str = "fixture"
    blob_root: Path = BACKEND_ROOT / "runs"
    cache_root: Path = BACKEND_ROOT / "runs/cache"
    cassette_root: Path = BACKEND_ROOT / "tests/cassettes"
    live_enabled_sources: str = ""
    http_connect_timeout_s: float = 4.0
    http_read_timeout_s: float = 8.0
    live_budget_s: float = 12.0
    dashboard_dist: Path = BACKEND_ROOT / "dashboard/dist"
    risk_zone_engine_enabled: bool = True
    risk_zone_node_bin: str = "node"
    risk_zone_bridge: Path = PROJECT_ROOT / "engines/risk-zone/dist/risk-zone-bridge.mjs"
    risk_zone_timeout_s: float = 30.0
    enable_local_docs: bool = False
    local_dashboard_origins: str = (
        "http://127.0.0.1:3100,http://localhost:3100,"
        "http://127.0.0.1:5173,http://localhost:5173"
    )

    def allowed_mcp_hosts(self) -> list[str]:
        return [host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()]

    def dashboard_origins(self) -> list[str]:
        return [
            origin.strip() for origin in self.local_dashboard_origins.split(",") if origin.strip()
        ]

    def enabled_live_sources(self) -> set[str]:
        return {source.strip() for source in self.live_enabled_sources.split(",") if source.strip()}


def load_settings() -> Settings:
    """Load environment settings once at the application composition root."""

    return Settings()


def export_legacy_collector_credentials(settings: Settings) -> None:
    """Bridge validated settings to legacy collectors that still read process env."""

    values = {
        "NIFS_JELLY_KEY": settings.nifs_jelly_key,
        "NIFS_REDTIDE_KEY": settings.nifs_redtide_key,
        "NIFS_SOO_KEY": settings.nifs_soo_key,
        "KHOA_SERVICE_KEY": settings.khoa_key,
    }
    for key, value in values.items():
        if value:
            os.environ[key] = value
