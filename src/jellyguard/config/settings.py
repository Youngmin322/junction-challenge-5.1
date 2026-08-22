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
    enable_local_docs: bool = False

    def allowed_mcp_hosts(self) -> list[str]:
        return [host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()]


def load_settings() -> Settings:
    """Load environment settings once at the application composition root."""

    return Settings()
