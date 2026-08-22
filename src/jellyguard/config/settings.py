from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JELLYGUARD_",
        env_file=".env",
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
    blob_root: Path = Path("./runs")
    cache_root: Path = Path("./runs/cache")
    cassette_root: Path = Path("./tests/cassettes")
    live_enabled_sources: str = ""
    http_connect_timeout_s: float = 4.0
    http_read_timeout_s: float = 8.0
    live_budget_s: float = 12.0
    dashboard_dist: Path = Path("./dashboard/dist")
    enable_local_docs: bool = False
    local_dashboard_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

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
