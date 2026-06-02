from fastapi.testclient import TestClient

from strataone.api import app


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_artifact_endpoint_generates_bundle() -> None:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})

    response = client.post("/sites/branch-001/artifacts")

    assert response.status_code == 200
    assert response.json()["site_name"] == "branch-001"
