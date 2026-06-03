from fastapi.testclient import TestClient

from strataone.api import app


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint_points_to_docs_and_dashboard() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["name"] == "StrataOne API"
    assert response.json()["docs"] == "/docs"


def test_plan_endpoint_accepts_site_payload() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()

    response = client.post("/sites/plan", json={"site": site})

    assert response.status_code == 200
    assert response.json()["site_name"] == "branch-001"


def test_preflight_endpoint_returns_config_only_readiness() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()

    response = client.post("/sites/preflight", json={"site": site})

    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_persistent_site_job_and_provider_endpoints() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()

    create_response = client.post("/sites", json={"site": site})
    providers_response = client.get("/providers")
    jobs_response = client.post("/sites/branch-001/jobs/validate")

    assert create_response.status_code == 200
    assert create_response.json()["name"] == "branch-001"
    assert providers_response.status_code == 200
    assert any(provider["name"] == "generic-redfish" for provider in providers_response.json()["providers"])
    assert jobs_response.status_code == 200
    assert "job_id" in jobs_response.json()


def test_site_validation_rejects_invalid_bmc_ip() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    site["hardware"]["nodes"][0]["bmc_ip"] = "not-an-ip"

    response = client.post("/sites", json={"site": site})

    assert response.status_code == 422
    assert "bmc_ip" in response.json()["detail"]


def test_mount_iso_job_requires_iso_contract() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})

    response = client.post(
        "/sites/branch-001/jobs/mount-iso",
        json={
            "username": "admin",
            "password": "secret",
            "iso_url": "https://repo.example.com/azure-local.iso",
            "boot_once": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approval-required"
    assert "approval_id" in response.json()


def test_settings_endpoint_returns_enterprise_sections() -> None:
    client = TestClient(app)

    response = client.get("/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["mode"] == "sqlite"
    assert "roles" in payload["access"]
    assert "hardware" in payload["providers"]


def test_access_api_creates_roles_and_users() -> None:
    client = TestClient(app)

    role_response = client.post(
        "/access/roles",
        json={"name": "Change Manager", "description": "Approves deployment windows", "permissions": ["approve-runs"]},
    )
    assert role_response.status_code == 200
    assert role_response.json()["name"] == "Change Manager"

    user_response = client.post(
        "/access/users",
        json={
            "username": "j.smith",
            "display_name": "Jane Smith",
            "email": "jane.smith@example.com",
            "roles": ["Change Manager"],
            "status": "active",
            "password": "CorrectHorseBatteryStaple!",
        },
    )
    assert user_response.status_code == 200
    assert user_response.json()["roles"] == ["Change Manager"]
    assert user_response.json()["password_configured"] is True

    settings_response = client.get("/settings")
    access = settings_response.json()["access"]
    assert any(role["name"] == "Change Manager" for role in access["roles"])
    assert any(user["username"] == "j.smith" for user in access["users"])


def test_password_login_issues_session_token(monkeypatch) -> None:
    client = TestClient(app)
    client.post(
        "/access/roles",
        json={"name": "Login Operator", "description": "Can read sites", "permissions": ["read-sites"]},
    )
    client.post(
        "/access/users",
        json={
            "username": "login.user",
            "display_name": "Login User",
            "email": "login.user@example.com",
            "roles": ["Login Operator"],
            "status": "active",
            "password": "StrataOneLogin123!",
        },
    )
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")

    login_response = client.post("/auth/login", json={"username": "login.user", "password": "StrataOneLogin123!"})
    token = login_response.json()["token"]
    sites_response = client.get("/sites", headers={"Authorization": f"Bearer {token}"})

    assert login_response.status_code == 200
    assert login_response.json()["username"] == "login.user"
    assert sites_response.status_code == 200


def test_logout_revokes_password_session(monkeypatch) -> None:
    client = TestClient(app)
    client.post(
        "/access/roles",
        json={"name": "Logout Reader", "description": "Can read sites", "permissions": ["read-sites"]},
    )
    client.post(
        "/access/users",
        json={
            "username": "logout.user",
            "display_name": "Logout User",
            "email": "logout.user@example.com",
            "roles": ["Logout Reader"],
            "status": "active",
            "password": "StrataOneLogout123!",
        },
    )
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    token = client.post("/auth/login", json={"username": "logout.user", "password": "StrataOneLogout123!"}).json()["token"]

    logout_response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    sites_response = client.get("/sites", headers={"Authorization": f"Bearer {token}"})

    assert logout_response.json()["revoked"] is True
    assert sites_response.status_code == 401


def test_session_admin_can_list_and_revoke_sessions(monkeypatch) -> None:
    client = TestClient(app)
    client.post(
        "/access/users",
        json={
            "username": "session.admin",
            "display_name": "Session Admin",
            "email": "session.admin@example.com",
            "roles": ["Platform Admin"],
            "status": "active",
            "password": "StrataOneSession123!",
        },
    )
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    token = client.post("/auth/login", json={"username": "session.admin", "password": "StrataOneSession123!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    sessions = client.get("/auth/sessions", headers=headers).json()["sessions"]
    session = next(item for item in sessions if item["username"] == "session.admin")
    revoked = client.delete(f"/auth/sessions/{session['id']}", headers=headers)

    assert session["token_fingerprint"]
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True


def test_audit_provider_config_and_job_events() -> None:
    client = TestClient(app)

    provider_response = client.get("/providers/generic-redfish")
    config_response = client.post("/providers/generic-redfish/config", json={"config": {"endpoint_mode": "redfish"}})
    audit_response = client.get("/audit")

    assert provider_response.status_code == 200
    assert config_response.status_code == 200
    assert config_response.json()["config"]["endpoint_mode"] == "redfish"
    assert audit_response.status_code == 200
    assert "audit" in audit_response.json()


def test_provider_test_endpoint_reports_configuration_state() -> None:
    client = TestClient(app)

    response = client.post("/providers/generic-redfish/test")

    assert response.status_code == 200
    assert response.json()["provider"] == "generic-redfish"
    assert any(check["name"] == "provider_registered" for check in response.json()["checks"])


def test_secret_reference_registry_round_trips() -> None:
    client = TestClient(app)

    saved = client.post(
        "/secrets",
        json={
            "name": "branch-bmc",
            "type": "bmc",
            "provider": "file",
            "reference": "secret://branch/bmc",
            "metadata": {"rotation": "quarterly"},
        },
    )
    listed = client.get("/secrets")

    assert saved.status_code == 200
    assert saved.json()["name"] == "branch-bmc"
    assert any(secret["name"] == "branch-bmc" for secret in listed.json()["secrets"])


def test_discovery_planner_returns_bounded_candidates() -> None:
    client = TestClient(app)

    response = client.post(
        "/discovery",
        json={"name": "Lab scan", "cidr": "10.0.0.0/29", "provider": "generic-redfish", "credential_ref": "branch-bmc"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "planned"
    assert payload["result"]["candidate_count"] == 6
    assert payload["result"]["candidates"][0]["status"] == "pending-scan"


def test_discovery_execute_marks_candidates_ready_when_live_disabled() -> None:
    client = TestClient(app)
    planned = client.post(
        "/discovery",
        json={"name": "Ready scan", "cidr": "10.0.1.0/30", "provider": "generic-redfish"},
    ).json()

    executed = client.post(f"/discovery/{planned['id']}/execute")

    assert executed.status_code == 200
    assert executed.json()["status"] == "ready-for-live-scan"
    assert executed.json()["result"]["candidates"][0]["status"] == "scan-ready"


def test_discovery_run_can_be_deleted() -> None:
    client = TestClient(app)
    planned = client.post(
        "/discovery",
        json={"name": "Delete scan", "cidr": "10.0.2.0/30", "provider": "generic-redfish"},
    ).json()

    deleted = client.delete(f"/discovery/{planned['id']}")

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_iso_registry_round_trips() -> None:
    client = TestClient(app)

    saved = client.post(
        "/isos",
        json={"name": "azure-local-test", "uri": "https://repo.example.com/azure-local.iso", "checksum": "abc123"},
    )
    listed = client.get("/isos")

    assert saved.status_code == 200
    assert saved.json()["name"] == "azure-local-test"
    assert any(iso["name"] == "azure-local-test" for iso in listed.json()["isos"])


def test_job_cancel_and_retry_endpoints() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})
    created = client.post("/sites/branch-001/jobs/validate").json()

    canceled = client.post(f"/jobs/{created['job_id']}/cancel")
    retried = client.post(f"/jobs/{created['job_id']}/retry")

    assert canceled.status_code == 200
    assert canceled.json()["status"] in {"canceled", "succeeded", "failed"}
    assert retried.status_code == 200
    assert "job_id" in retried.json()


def test_provider_detail_includes_configuration_template() -> None:
    client = TestClient(app)

    response = client.get("/providers/azure-local")

    assert response.status_code == 200
    assert response.json()["template"]["credential_ref"] == "azure-local-spn"


def test_approval_can_be_rejected() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})

    requested = client.post(
        "/sites/branch-001/jobs/mount-iso",
        json={"iso_url": "https://repo.example.com/azure-local.iso", "boot_once": True},
    )
    approval_id = requested.json()["approval_id"]
    rejected = client.post(f"/approvals/{approval_id}/reject", json={"reason": "maintenance window closed"})

    assert requested.json()["status"] == "approval-required"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["detail"]["rejection_reason"] == "maintenance window closed"


def test_approval_can_be_approved_and_run() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})

    requested = client.post("/sites/branch-001/jobs/deploy-azure-local", json={})
    approval_id = requested.json()["approval_id"]
    queued = client.post(f"/approvals/{approval_id}/run")

    assert requested.json()["status"] == "approval-required"
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert "job_id" in queued.json()


def test_artifact_files_can_be_listed_and_read() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})
    client.post("/sites/branch-001/artifacts")

    listing = client.get("/sites/branch-001/artifacts/files")
    manifest = client.get("/sites/branch-001/artifacts/files/manifest.json")

    assert listing.status_code == 200
    assert any(file["name"] == "manifest.json" for file in listing.json()["files"])
    assert manifest.status_code == 200
    assert "branch-001" in manifest.json()["content"]


def test_provider_api_creates_custom_provider() -> None:
    client = TestClient(app)

    response = client.post(
        "/providers",
        json={
            "name": "Acme Redfish",
            "type": "hardware",
            "description": "ACME supported Redfish provider",
            "vendor_supported": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "acme-redfish"
    assert payload["editable"] is True
    assert payload["vendor_supported"] is True

    providers = client.get("/providers").json()["providers"]
    assert any(provider["name"] == "acme-redfish" for provider in providers)
    assert client.delete("/providers/acme-redfish").json()["deleted"] is True


def test_artifact_endpoint_generates_bundle() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})

    response = client.post("/sites/branch-001/artifacts")

    assert response.status_code == 200
    assert response.json()["site_name"] == "branch-001"


def test_inventory_can_be_saved_and_returned() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})
    inventory = {
        "site_name": "branch-001",
        "provider": "generic-redfish",
        "nodes": [
            {
                "serial": "ABC123",
                "bmc_ip": "10.10.1.11",
                "reachable": True,
                "capabilities": ["boot-override", "virtual-media", "firmware-inventory"],
            }
        ],
    }

    save_response = client.post("/sites/branch-001/inventory", json={"inventory": inventory})
    get_response = client.get("/sites/branch-001/inventory")

    assert save_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json()["reachable_nodes"] == 1


def test_auth_enforcement_rejects_missing_token(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "test-bootstrap")
    client = TestClient(app)

    response = client.get("/sites")

    assert response.status_code == 401


def test_auth_enforcement_accepts_bootstrap_token(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "test-bootstrap")
    client = TestClient(app)

    response = client.get("/sites", headers={"Authorization": "Bearer test-bootstrap"})

    assert response.status_code == 200


def test_rbac_rejects_valid_token_without_permission(monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "test-bootstrap")
    monkeypatch.setenv("STRATAONE_API_TOKENS", "viewer-token=viewer:Viewer")
    client = TestClient(app)

    response = client.post(
        "/providers",
        headers={"Authorization": "Bearer viewer-token"},
        json={"name": "Blocked Provider", "type": "hardware", "description": "Should not save"},
    )

    assert response.status_code == 403
