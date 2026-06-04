import time

from fastapi.testclient import TestClient

from strataone.api import app


def _client_with_site() -> TestClient:
    client = TestClient(app)
    site = client.get("/sites/example").json()
    client.post("/sites", json={"site": site})
    return client


def test_templates_topology_compatibility_and_releases() -> None:
    client = _client_with_site()

    templates = client.get("/templates")
    topology = client.get("/sites/branch-001/topology")
    compatibility = client.get("/compatibility")
    releases = client.get("/releases")

    assert templates.status_code == 200
    assert any(item["id"] == "azure-local-branch" for item in templates.json()["templates"])
    assert topology.status_code == 200
    assert any(node["type"] == "host" for node in topology.json()["nodes"])
    assert compatibility.status_code == 200
    assert any(item["name"] == "generic-redfish" for item in compatibility.json()["hardware"])
    assert releases.status_code == 200
    assert any(item["version"] == "0.3.0-preview" for item in releases.json()["releases"])


def test_artifact_zip_and_iac_outputs() -> None:
    client = _client_with_site()

    generated = client.post("/sites/branch-001/artifacts")
    listing = client.get("/sites/branch-001/artifacts/files")
    bundle = client.get("/sites/branch-001/artifacts/bundle.zip")

    assert generated.status_code == 200
    names = {item["name"] for item in listing.json()["files"]}
    assert {"main.tf", "azure-local.bicep", "ansible-inventory.yml", "ansible-playbook.yml"}.issubset(names)
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    assert len(bundle.content) > 100


def test_notification_and_gitops_contracts() -> None:
    client = _client_with_site()

    notification = client.post(
        "/notifications/test",
        json={"type": "webhook", "name": "ops", "target": "https://hooks.example.com/strataone", "send": False},
    )
    export = client.post("/gitops/export", json={"site_name": "branch-001", "format": "yaml", "path": "sites/branch-001.yaml"})
    imported = client.post("/gitops/import", json={"content": export.json()["files"][0]["content"], "source": "test"})

    assert notification.status_code == 200
    assert notification.json()["status"] == "ready"
    assert export.status_code == 200
    assert export.json()["files"][0]["path"] == "sites/branch-001.yaml"
    assert imported.status_code == 200
    assert imported.json()["name"] == "branch-001"


def test_job_websocket_stream_returns_events() -> None:
    client = _client_with_site()
    created = client.post("/sites/branch-001/jobs/validate")
    job_id = created.json()["job_id"]
    for _ in range(20):
        if client.get(f"/jobs/{job_id}/events").json()["events"]:
            break
        time.sleep(0.05)

    with client.websocket_connect(f"/jobs/{job_id}/events/ws") as websocket:
        message = websocket.receive_json()

    assert message["type"] in {"job-event", "job-complete"}
