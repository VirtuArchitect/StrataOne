import os
from pathlib import Path

from fastapi.testclient import TestClient

from strataone.api import app, validate_secure_runtime_defaults
from strataone.security import RateLimitMiddleware


def test_security_headers_are_emitted() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in response.headers


def test_rate_limit_blocks_burst(monkeypatch) -> None:
    RateLimitMiddleware._buckets.clear()
    monkeypatch.setenv("STRATAONE_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("STRATAONE_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    limited = client.get("/health")

    assert limited.status_code == 429
    assert limited.headers["Retry-After"]


def test_tenant_scoped_token_only_lists_own_sites(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "bootstrap")
    monkeypatch.setenv("STRATAONE_API_TOKENS", "tenant-a=tenant.a:Deployment Admin,Viewer@tenant-a;tenant-b=tenant.b:Deployment Admin,Viewer@tenant-b")
    client = TestClient(app)
    example = client.get("/sites/example", headers={"Authorization": "Bearer bootstrap"}).json()
    site_a = {**example, "site": {**example["site"], "name": "tenant-a-site"}}
    site_b = {**example, "site": {**example["site"], "name": "tenant-b-site"}}

    create_a = client.post("/sites", json={"site": site_a}, headers={"Authorization": "Bearer tenant-a"})
    create_b = client.post("/sites", json={"site": site_b}, headers={"Authorization": "Bearer tenant-b"})
    list_a = client.get("/sites", headers={"Authorization": "Bearer tenant-a"})
    get_b_from_a = client.get("/sites/tenant-b-site", headers={"Authorization": "Bearer tenant-a"})

    assert create_a.status_code == 200
    assert create_b.status_code == 200
    listed_names = [site["name"] for site in list_a.json()["sites"]]
    assert "tenant-a-site" in listed_names
    assert "tenant-b-site" not in listed_names
    assert get_b_from_a.status_code == 404


def test_tenant_scoped_token_cannot_read_other_tenant_job(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "bootstrap")
    monkeypatch.setenv("STRATAONE_REQUIRE_APPROVALS", "false")
    monkeypatch.setenv("STRATAONE_API_TOKENS", "tenant-a=tenant.a:Deployment Admin,Operator,Viewer@tenant-a;tenant-b=tenant.b:Deployment Admin,Operator,Viewer@tenant-b")
    client = TestClient(app)
    example = client.get("/sites/example", headers={"Authorization": "Bearer bootstrap"}).json()
    site_a = {**example, "site": {**example["site"], "name": "tenant-a-job-site"}}

    create_a = client.post("/sites", json={"site": site_a}, headers={"Authorization": "Bearer tenant-a"})
    job_response = client.post("/sites/tenant-a-job-site/jobs/validate", json={}, headers={"Authorization": "Bearer tenant-a"})
    job_id = job_response.json()["job_id"]

    get_from_b = client.get(f"/jobs/{job_id}", headers={"Authorization": "Bearer tenant-b"})
    events_from_b = client.get(f"/jobs/{job_id}/events", headers={"Authorization": "Bearer tenant-b"})

    assert create_a.status_code == 200
    assert job_response.status_code == 200
    assert get_from_b.status_code == 404
    assert events_from_b.status_code == 404


def test_site_name_rejects_path_traversal() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    site["site"]["name"] = "..\\outside"

    response = client.post("/sites", json={"site": site})

    assert response.status_code == 422
    assert "site name" in response.json()["detail"]


def test_outbound_url_actions_block_localhost_targets() -> None:
    client = TestClient(app)

    iso = client.post("/isos", json={"name": "local-iso", "uri": "http://127.0.0.1:8080/private.iso"})
    validate_iso = client.post("/isos/local-iso/validate")
    webhook = client.post(
        "/notifications/test",
        json={"type": "webhook", "target": "http://localhost:8080/hook", "send": False},
    )

    assert iso.status_code == 200
    assert validate_iso.status_code == 422
    assert webhook.status_code == 422


def test_production_startup_rejects_placeholder_secrets(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_ENVIRONMENT", "production")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "change-this-token")
    monkeypatch.setenv("STRATAONE_ADMIN_PASSWORD", "change-this-password")
    monkeypatch.setenv("POSTGRES_PASSWORD", "strataone")

    try:
        validate_secure_runtime_defaults()
    except RuntimeError as exc:
        message = str(exc)
    else:
        message = ""

    assert "STRATAONE_BOOTSTRAP_TOKEN" in message
    assert "STRATAONE_ADMIN_PASSWORD" in message
    assert "POSTGRES_PASSWORD" in message


def test_provider_validation_harness_records_contract_run() -> None:
    client = TestClient(app)

    response = client.post(
        "/providers/generic-redfish/validation/run",
        json={"operation": "redfish-virtual-media", "target": "mock-bmc", "live": False},
    )
    detail = client.get("/providers/generic-redfish")

    assert response.status_code == 200
    assert response.json()["status"] == "passed"
    assert response.json()["mode"] == "contract"
    assert any(run["id"] == response.json()["id"] for run in detail.json()["validation_runs"])


def test_provider_validation_harness_blocks_live_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_ENABLE_LIVE_REDFISH", "false")
    client = TestClient(app)

    response = client.post(
        "/providers/generic-redfish/validation/run",
        json={"operation": "redfish-virtual-media", "target": "10.0.0.10", "live": True},
    )

    assert response.status_code == 409


def test_ci_and_proxy_artifacts_exist() -> None:
    root = Path(__file__).resolve().parents[1]

    assert (root / ".github" / "workflows" / "ci.yml").exists()
    assert (root / "deploy" / "nginx" / "proxy.conf").exists()
    assert (root / "deploy" / "nginx" / "dashboard.conf").exists()
