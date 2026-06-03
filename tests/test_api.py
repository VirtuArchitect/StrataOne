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
        },
    )
    assert user_response.status_code == 200
    assert user_response.json()["roles"] == ["Change Manager"]

    settings_response = client.get("/settings")
    access = settings_response.json()["access"]
    assert any(role["name"] == "Change Manager" for role in access["roles"])
    assert any(user["username"] == "j.smith" for user in access["users"])


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
