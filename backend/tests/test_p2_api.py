from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jellyguard.api import create_app
from jellyguard.config.settings import Settings


def settings(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        local_rest_key="local-secret",
        mcp_client_key="mcp-secret",
        blob_root=tmp_path / "runs",
        cache_root=tmp_path / "cache",
        dashboard_dist=Path("dashboard/dist"),
        **overrides,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/sources/status",
        "/v1/dashboard/bootstrap",
        "/v1/hanul/runs/unknown",
        "/v1/hanul/explain?run_id=unknown",
        "/v1/datasets",
        "/v1/datasets/jellyfish/status",
        "/v1/datasets/risk_zone/quality",
    ],
)
def test_new_local_rest_routes_require_key(tmp_path, path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get(path).status_code == 401
        assert (
            client.get(path, headers={"x-jellyguard-local-key": "local-secret"}).status_code == 200
        )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/sources/status",
        "/v1/dashboard/bootstrap",
        "/v1/hanul/runs/unknown",
        "/v1/hanul/explain?run_id=unknown",
        "/v1/datasets",
        "/v1/datasets/jellyfish/status",
        "/v1/datasets/risk_zone/quality",
    ],
)
def test_new_routes_are_hidden_on_external_tunnel_host(tmp_path, path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get(
            path,
            headers={"host": "demo.devtunnels.ms", "x-jellyguard-local-key": "local-secret"},
        )
        assert response.status_code == 404


def test_source_status_and_bootstrap_are_public_projection_only(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        headers = {"x-jellyguard-local-key": "local-secret"}
        sources = client.get("/v1/sources/status", headers=headers).json()
        bootstrap = client.get("/v1/dashboard/bootstrap", headers=headers).json()
        assert len(sources["data"]["sources"]) == 12
        assert bootstrap["data"]["dashboard_contract"] == "offline_public_watch_cells_v1"
        serialized = str(bootstrap)
        assert "nifs_jelly_key" not in serialized
        assert "khoa_key" not in serialized


def test_integrated_dataset_catalog_reports_fixture_and_risk_engine(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        headers = {"x-jellyguard-local-key": "local-secret"}
        payload = client.get("/v1/datasets", headers=headers).json()
        datasets = {item["id"]: item for item in payload["datasets"]}
        assert set(datasets) == {
            "jellyfish",
            "ocean_current",
            "marine_environment",
            "risk_zone",
        }
        assert datasets["jellyfish"]["connection"] == "credentials_required"
        assert datasets["risk_zone"]["connection"] == "synthetic_ready"
        quality = client.get("/v1/datasets/risk_zone/quality", headers=headers).json()
        assert quality["ready"] is True
        assert quality["mode"] == "synthetic"


def test_unknown_dataset_returns_404(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get(
            "/v1/datasets/unknown/status",
            headers={"x-jellyguard-local-key": "local-secret"},
        )
        assert response.status_code == 404


def test_dashboard_assets_are_served_without_rest_key(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert "JellyGuard" in response.text


def test_dashboard_has_no_external_runtime_dependency():
    dashboard = Path("dashboard/dist")
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in dashboard.rglob("*") if path.is_file()
    )
    assert "https://" not in text
    assert "http://" not in text


def test_zone_public_contract_has_no_facility_geometry(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        payload = client.get(
            "/v1/hanul/zones", headers={"x-jellyguard-local-key": "local-secret"}
        ).json()
        for zone in payload["data"]["zones"]:
            assert zone["facility_geometry"] is None
            assert zone["access_class"] == "public"
            assert zone["display_name"].startswith("감시격자")
