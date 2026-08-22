from fastapi.testclient import TestClient

from jellyguard.api import create_app
from jellyguard.config.settings import Settings

PROVIDER_ENV_NAMES = (
    "JELLYGUARD_NIFS_JELLY_KEY",
    "JELLYGUARD_NIFS_REDTIDE_KEY",
    "JELLYGUARD_NIFS_SOO_KEY",
    "JELLYGUARD_KHOA_KEY",
)


def test_provider_key_environment_is_really_empty(monkeypatch):
    for name in PROVIDER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.nifs_jelly_key is None
    assert settings.nifs_redtide_key is None
    assert settings.nifs_soo_key is None
    assert settings.khoa_key is None


def test_server_boots_without_provider_keys_and_rest_works():
    app = create_app(Settings(_env_file=None, local_rest_key="local-secret"))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/v1/observations/search",
            json={"allowed_modes": ["CACHED"], "include_scenario_seeds": False},
            headers={"x-jellyguard-local-key": "local-secret"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "READY"


def test_mcp_never_opens_without_application_key():
    app = create_app(Settings(_env_file=None, mcp_client_key=None))
    with TestClient(app) as client:
        assert client.post("/mcp", json={}).status_code == 503


def test_wrong_mcp_key_is_rejected():
    app = create_app(Settings(_env_file=None, mcp_client_key="correct"))
    with TestClient(app) as client:
        assert (
            client.post("/mcp", json={}, headers={"x-mcp-client-key": "wrong"}).status_code == 401
        )


def test_external_tunnel_host_can_only_reach_mcp_path():
    app = create_app(
        Settings(
            _env_file=None,
            mcp_client_key="correct",
            local_rest_key="local-secret",
            mcp_allowed_hosts="demo-8000.region.devtunnels.ms",
        )
    )
    with TestClient(app, base_url="https://demo-8000.region.devtunnels.ms") as client:
        assert client.get("/v1/hanul/zones").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.post("/mcp", json={}).status_code == 401


def test_local_rest_and_external_policy_do_not_share_auth_surface():
    app = create_app(
        Settings(_env_file=None, mcp_client_key="correct", local_rest_key="local-secret")
    )
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/v1/hanul/zones").status_code == 401
        assert (
            client.get(
                "/v1/hanul/zones", headers={"x-jellyguard-local-key": "local-secret"}
            ).status_code
            == 200
        )


def test_spoofed_localhost_host_cannot_bypass_rest_auth():
    app = create_app(
        Settings(_env_file=None, mcp_client_key="correct", local_rest_key="local-secret")
    )
    with TestClient(app, base_url="https://demo-8000.region.devtunnels.ms") as client:
        response = client.get("/v1/hanul/zones", headers={"host": "localhost"})
        assert response.status_code == 401


def test_provider_keys_never_enter_response(tmp_path):
    secret = "provider-secret-must-not-leak"
    app = create_app(
        Settings(
            _env_file=None,
            nifs_jelly_key=secret,
            khoa_key=secret,
            local_rest_key="local-secret",
            blob_root=tmp_path,
        )
    )
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/v1/observations/search",
            json={"allowed_modes": ["CACHED"]},
            headers={"x-jellyguard-local-key": "local-secret"},
        )
        assert response.status_code == 200
        assert secret not in response.text


def test_local_dashboard_origin_gets_cors_but_unknown_origin_does_not(tmp_path):
    app = create_app(Settings(_env_file=None, local_rest_key="local-secret", blob_root=tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        allowed = client.options(
            "/v1/hanul/zones",
            headers={
                "origin": "http://localhost:5173",
                "access-control-request-method": "GET",
                "access-control-request-headers": "x-jellyguard-local-key",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"

        denied = client.options(
            "/v1/hanul/zones",
            headers={
                "origin": "https://untrusted.example",
                "access-control-request-method": "GET",
            },
        )
        assert "access-control-allow-origin" not in denied.headers
