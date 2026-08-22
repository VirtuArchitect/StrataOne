import time
from pathlib import Path

from strataone.inventory import InventoryReport, NodeInventory
from strataone.jobs import JobRunner
from strataone.store import StrataStore
from strataone.state import load_site_spec


def test_store_persists_sites_and_jobs(tmp_path: Path) -> None:
    store = StrataStore(tmp_path / "strataone.db")
    spec = load_site_spec(Path("examples/azure-local-branch.yaml"))

    site = store.upsert_site(spec)
    job = store.create_job(site.name, "validate")
    store.start_job(job.id)
    store.finish_job(job.id, {"valid": True})

    assert store.get_site("branch-001") is not None
    assert store.get_job(job.id).status == "succeeded"
    assert store.list_jobs("branch-001")[0].result == {"valid": True}


def test_job_runner_executes_plan_job(tmp_path: Path) -> None:
    store = StrataStore(tmp_path / "strataone.db")
    store.upsert_site(load_site_spec(Path("examples/azure-local-branch.yaml")))
    runner = JobRunner(store)

    job_id = runner.submit("branch-001", "plan")

    for _ in range(20):
        job = store.get_job(job_id)
        if job and job.status == "succeeded":
            break
        time.sleep(0.05)

    job = store.get_job(job_id)
    assert job.status == "succeeded"
    assert job.result["site_name"] == "branch-001"
    assert any(event.message == "Job completed" for event in store.list_job_events(job_id))


def test_job_runner_executes_lifecycle_and_azure_local_contracts(tmp_path: Path) -> None:
    store = StrataStore(tmp_path / "strataone.db")
    store.upsert_site(load_site_spec(Path("examples/azure-local-branch.yaml")))
    runner = JobRunner(store)

    drift_id = runner.submit("branch-001", "drift-detect")
    deploy_id = runner.submit("branch-001", "deploy-azure-local", {"approval_id": "approved"})

    for _ in range(30):
        drift = store.get_job(drift_id)
        deploy = store.get_job(deploy_id)
        if drift and deploy and drift.status == "succeeded" and deploy.status == "succeeded":
            break
        time.sleep(0.05)

    assert store.get_job(drift_id).result["action"] == "drift-detect"
    assert store.get_job(deploy_id).result["stages"][0]["name"] == "validate-prerequisites"


def test_job_runner_can_leave_jobs_for_durable_worker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_EXECUTION_MODE", "queued")
    store = StrataStore(tmp_path / "strataone.db")
    store.upsert_site(load_site_spec(Path("examples/azure-local-branch.yaml")))
    runner = JobRunner(store)

    job_id = runner.submit("branch-001", "validate", {"trace": "persisted"})

    queued = store.get_job(job_id)
    assert queued.status == "queued"
    assert queued.params == {"trace": "persisted"}

    claimed = runner.run_queued_once()

    job = store.get_job(job_id)
    assert claimed == job_id
    assert job.status == "succeeded"
    assert job.result["valid"] is True


def test_queued_inventory_rejects_inline_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_EXECUTION_MODE", "queued")
    store = StrataStore(tmp_path / "strataone.db")
    store.upsert_site(load_site_spec(Path("examples/azure-local-branch.yaml")))
    runner = JobRunner(store)

    try:
        runner.submit("branch-001", "inventory", {"username": "admin", "password": "secret"})
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("queued inventory accepted inline credentials")

    assert "credential_ref" in message
    assert store.list_jobs("branch-001") == []


def test_queued_inventory_accepts_credential_ref(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STRATAONE_EXECUTION_MODE", "queued")
    store = StrataStore(tmp_path / "strataone.db")
    store.upsert_site(load_site_spec(Path("examples/azure-local-branch.yaml")))
    runner = JobRunner(store)

    job_id = runner.submit("branch-001", "inventory", {"credential_ref": "branch-bmc"})

    job = store.get_job(job_id)
    assert job.status == "queued"
    assert job.params == {"credential_ref": "branch-bmc"}


def test_job_runner_dispatches_queued_jobs_to_queue_backend(tmp_path: Path, monkeypatch) -> None:
    dispatched = []

    class FakeQueue:
        def enqueue(self, job_id: str) -> None:
            dispatched.append(job_id)

        def dequeue(self) -> str | None:
            return dispatched.pop(0) if dispatched else None

    monkeypatch.setenv("STRATAONE_EXECUTION_MODE", "queued")
    monkeypatch.setattr("strataone.jobs.get_job_queue", lambda: FakeQueue())
    store = StrataStore(tmp_path / "strataone.db")
    store.upsert_site(load_site_spec(Path("examples/azure-local-branch.yaml")))
    runner = JobRunner(store)

    job_id = runner.submit("branch-001", "validate")

    assert dispatched == [job_id]
    assert store.get_job(job_id).status == "queued"
    assert runner.run_queued_once() == job_id
    assert store.get_job(job_id).status == "succeeded"


def test_preflight_job_uses_latest_stored_inventory(tmp_path: Path) -> None:
    store = StrataStore(tmp_path / "strataone.db")
    spec = load_site_spec(Path("examples/azure-local-branch.yaml"))
    store.upsert_site(spec)
    store.save_inventory(
        InventoryReport(
            site_name="branch-001",
            provider="generic-redfish",
            nodes=[
                NodeInventory(serial="ABC123", bmc_ip="10.10.1.11", reachable=False, error="timeout"),
                NodeInventory(serial="ABC124", bmc_ip="10.10.1.12", reachable=True, capabilities=["boot-override"]),
            ],
        )
    )
    runner = JobRunner(store)

    job_id = runner.submit("branch-001", "preflight")

    for _ in range(20):
        job = store.get_job(job_id)
        if job and job.status == "succeeded":
            break
        time.sleep(0.05)

    job = store.get_job(job_id)
    assert job.status == "succeeded"
    assert job.result["ready"] is False
    assert any(check["name"] == "ABC123-bmc" and check["status"] == "FAIL" for check in job.result["checks"])
