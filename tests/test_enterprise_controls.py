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


def test_tenant_scoped_token_only_lists_and_imports_own_discovery(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "bootstrap")
    monkeypatch.setenv("STRATAONE_API_TOKENS", "tenant-a=tenant.a:Deployment Admin,Operator,Viewer@tenant-a;tenant-b=tenant.b:Deployment Admin,Operator,Viewer@tenant-b")
    client = TestClient(app)

    created = client.post(
        "/discovery",
        json={"name": "Tenant A scan", "cidr": "10.20.30.0/30", "provider": "generic-redfish"},
        headers={"Authorization": "Bearer tenant-a"},
    )
    run_id = created.json()["id"]
    list_a = client.get("/discovery", headers={"Authorization": "Bearer tenant-a"})
    list_b = client.get("/discovery", headers={"Authorization": "Bearer tenant-b"})
    execute_from_b = client.post(f"/discovery/{run_id}/execute", headers={"Authorization": "Bearer tenant-b"})
    import_from_b = client.post(
        f"/discovery/{run_id}/import",
        json={"site_name": "tenant-b-imported", "location": "lab", "selected_bmc_ips": ["10.20.30.1"]},
        headers={"Authorization": "Bearer tenant-b"},
    )
    import_from_a = client.post(
        f"/discovery/{run_id}/import",
        json={"site_name": "tenant-a-imported-discovery", "location": "lab", "selected_bmc_ips": ["10.20.30.1"]},
        headers={"Authorization": "Bearer tenant-a"},
    )
    get_imported_from_b = client.get("/sites/tenant-a-imported-discovery", headers={"Authorization": "Bearer tenant-b"})

    assert created.status_code == 200
    assert created.json()["tenant_id"] == "tenant-a"
    assert any(run["id"] == run_id for run in list_a.json()["runs"])
    assert all(run["id"] != run_id for run in list_b.json()["runs"])
    assert execute_from_b.status_code == 404
    assert import_from_b.status_code == 404
    assert import_from_a.status_code == 200
    assert import_from_a.json()["tenant_id"] == "tenant-a"
    assert get_imported_from_b.status_code == 404


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


def test_outbound_url_actions_block_redirects_to_private_targets(monkeypatch) -> None:
    client = TestClient(app)
    client.post("/isos", json={"name": "redirect-iso", "uri": "https://example.com/redirect.iso"})

    class RedirectResponse:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/private.iso"}
        is_redirect = True

        def close(self) -> None:
            return None

    monkeypatch.setattr("strataone.api.requests.request", lambda *args, **kwargs: RedirectResponse())

    response = client.post("/isos/redirect-iso/validate")

    assert response.status_code == 422
    assert "private or reserved" in response.json()["detail"]


def test_production_startup_rejects_placeholder_secrets(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_ENVIRONMENT", "production")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "change-this-token")
    monkeypatch.setenv("STRATAONE_ADMIN_PASSWORD", "change-this-password")
    monkeypatch.setenv("POSTGRES_PASSWORD", "strataone")
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "false")
    monkeypatch.setenv("STRATAONE_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("STRATAONE_EXECUTION_MODE", "queued")
    monkeypatch.setenv("STRATAONE_QUEUE_BACKEND", "memory")
    monkeypatch.setenv("STRATAONE_TENANT_ENFORCEMENT", "false")

    try:
        validate_secure_runtime_defaults()
    except RuntimeError as exc:
        message = str(exc)
    else:
        message = ""

    assert "STRATAONE_BOOTSTRAP_TOKEN" in message
    assert "STRATAONE_ADMIN_PASSWORD" in message
    assert "POSTGRES_PASSWORD" in message
    assert "STRATAONE_AUTH_ENABLED" in message
    assert "STRATAONE_STATE_BACKEND" in message
    assert "STRATAONE_QUEUE_BACKEND" in message
    assert "STRATAONE_TENANT_ENFORCEMENT" in message


def test_durable_job_approval_and_audit_details_redact_secrets(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_REQUIRE_APPROVALS", "true")
    client = TestClient(app)
    site = client.get("/sites/example").json()
    site["site"]["name"] = "redaction-site"
    client.post("/sites", json={"site": site})

    job = client.post(
        "/sites/redaction-site/jobs/validate",
        json={"username": "admin", "password": "super-secret-password"},
    ).json()
    stored_job = client.get(f"/jobs/{job['job_id']}").json()
    approval = client.post(
        "/sites/redaction-site/jobs/mount-iso",
        json={
            "username": "admin",
            "password": "approval-secret-password",
            "iso_url": "https://repo.example.com/azure-local.iso",
        },
    ).json()
    approvals = client.get("/approvals").json()["approvals"]
    client.post("/providers/generic-redfish/config", json={"config": {"password": "provider-secret", "credential_ref": "branch-bmc"}})
    audit = client.get("/audit?limit=10").json()["audit"]

    approval_record = next(item for item in approvals if item["id"] == approval["approval_id"])
    provider_audit = next(item for item in audit if item["action"] == "provider.config.upsert")
    assert stored_job["params"]["password"] == "***"
    assert stored_job["params"]["username"] == "admin"
    assert approval_record["detail"]["params"]["password"] == "***"
    assert provider_audit["detail"]["password"] == "***"
    assert provider_audit["detail"]["credential_ref"] == "***"


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
