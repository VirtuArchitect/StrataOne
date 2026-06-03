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
