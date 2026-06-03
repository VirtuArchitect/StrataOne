import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from strataone.artifacts import ArtifactGenerator
from strataone.inventory import InventoryReport
from strataone.jobs import JobRunner
from strataone.orchestrator import Orchestrator
from strataone.preflight import PreflightRunner
from strataone.providers.registry import list_providers
from strataone.store import StrataStore, spec_from_record
from strataone.state import SiteSpec, load_site_spec

class SitePayload(BaseModel):
    site: dict[str, Any]


class InventoryPayload(BaseModel):
    inventory: dict[str, Any]


class JobPayload(BaseModel):
    username: str | None = None
    password: str | None = None
    insecure: bool | None = None
    timeout: float | None = None


store = StrataStore()
jobs = JobRunner(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_example_site()
    yield


app = FastAPI(
    title="StrataOne API",
    version="0.1.0",
    description="API for vendor-agnostic, hypervisor-agnostic zero-touch orchestration.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _spec_from_payload(payload: SitePayload) -> SiteSpec:
    try:
        return SiteSpec.model_validate(payload.site)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "StrataOne API",
        "status": "ok",
        "dashboard": "http://localhost:8088",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/sites/example")
def example_site() -> dict[str, Any]:
    try:
        spec = load_site_spec(Path("examples/azure-local-branch.yaml"))
        return spec.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def seed_example_site() -> None:
    if store.list_sites():
        return
    try:
        store.upsert_site(load_site_spec(Path("examples/azure-local-branch.yaml")))
    except Exception:
        return


@app.get("/providers")
def providers() -> dict[str, Any]:
    return {"providers": [provider.model_dump(mode="json") for provider in list_providers()]}


@app.get("/settings")
def settings() -> dict[str, Any]:
    provider_list = list_providers()
    return {
        "general": {
            "instance_name": os.getenv("STRATAONE_INSTANCE_NAME", "StrataOne"),
            "environment": os.getenv("STRATAONE_ENVIRONMENT", "development"),
            "api_port": os.getenv("STRATAONE_API_PORT", "8080"),
            "dashboard_port": os.getenv("STRATAONE_DASHBOARD_PORT", "8088"),
        },
        "access": {
            "mode": "local-dev",
            "rbac_enforced": False,
            "oidc_enabled": bool(os.getenv("STRATAONE_OIDC_ISSUER")),
            "roles": [
                {"name": "Viewer", "permissions": ["read-sites", "read-jobs", "read-providers"]},
                {"name": "Operator", "permissions": ["run-inventory", "run-preflight", "generate-artifacts"]},
                {"name": "Deployment Admin", "permissions": ["create-sites", "update-sites", "run-plan"]},
                {"name": "Platform Admin", "permissions": ["manage-providers", "manage-settings"]},
                {"name": "Auditor", "permissions": ["read-audit", "export-reports"]},
            ],
        },
        "secrets": {
            "bmc_username_configured": bool(os.getenv("STRATAONE_BMC_USERNAME")),
            "bmc_password_configured": bool(os.getenv("STRATAONE_BMC_PASSWORD")),
            "dashboard_transient_credentials": True,
            "vault_provider": os.getenv("STRATAONE_VAULT_PROVIDER", "none"),
        },
        "database": {
            "mode": "sqlite",
            "path": str(store.path),
            "site_count": len(store.list_sites()),
            "job_count": len(store.list_jobs()),
        },
        "providers": {
            "plugin_dir": os.getenv("STRATAONE_PLUGIN_DIR", "plugins"),
            "hardware": [provider.model_dump(mode="json") for provider in provider_list if provider.type == "hardware"],
            "platform": [provider.model_dump(mode="json") for provider in provider_list if provider.type == "platform"],
        },
        "api": {
            "cors": "allow-all",
            "docs": "/docs",
            "health": "/health",
            "session_timeout_minutes": int(os.getenv("STRATAONE_SESSION_TIMEOUT_MINUTES", "60")),
        },
        "artifacts": {
            "output_dir": os.getenv("STRATAONE_ARTIFACT_DIR", ".strataone/artifacts"),
            "retention_days": int(os.getenv("STRATAONE_ARTIFACT_RETENTION_DAYS", "30")),
            "download_bundles_enabled": False,
        },
        "audit": {
            "enabled": False,
            "job_history_retention_days": int(os.getenv("STRATAONE_JOB_RETENTION_DAYS", "90")),
            "configuration_change_tracking": "planned",
        },
    }


@app.get("/sites")
def list_site_records() -> dict[str, Any]:
    return {"sites": [site.model_dump(mode="json") for site in store.list_sites()]}


@app.post("/sites")
def create_or_update_site(payload: SitePayload) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return store.upsert_site(spec).model_dump(mode="json")


@app.get("/sites/{site_name}")
def get_site_record(site_name: str) -> dict[str, Any]:
    site = store.get_site(site_name)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site.model_dump(mode="json")


@app.delete("/sites/{site_name}")
def delete_site_record(site_name: str) -> dict[str, bool]:
    return {"deleted": store.delete_site(site_name)}


@app.post("/sites/{site_name}/jobs/{action}")
def run_site_job(site_name: str, action: str, payload: JobPayload | None = None) -> dict[str, str]:
    if action not in {"validate", "plan", "inventory", "preflight", "artifacts"}:
        raise HTTPException(status_code=400, detail="unsupported action")
    if store.get_site(site_name) is None:
        raise HTTPException(status_code=404, detail="site not found")
    params = payload.model_dump(exclude_none=True) if payload else {}
    return {"job_id": jobs.submit(site_name, action, params)}


@app.get("/jobs")
def list_job_records(site_name: str | None = None) -> dict[str, Any]:
    return {"jobs": [job.model_dump(mode="json") for job in store.list_jobs(site_name)]}


@app.get("/jobs/{job_id}")
def get_job_record(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump(mode="json")


@app.post("/sites/{site_name}/artifacts")
def generate_artifacts(site_name: str) -> dict[str, Any]:
    site = store.get_site(site_name)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return ArtifactGenerator().generate(spec_from_record(site)).model_dump(mode="json")


@app.get("/sites/{site_name}/inventory")
def get_site_inventory(site_name: str) -> dict[str, Any]:
    inventory = store.get_inventory(site_name)
    if inventory is None:
        raise HTTPException(status_code=404, detail="inventory not found")
    return inventory.model_dump(mode="json")


@app.post("/sites/{site_name}/inventory")
def save_site_inventory(site_name: str, payload: InventoryPayload) -> dict[str, Any]:
    if store.get_site(site_name) is None:
        raise HTTPException(status_code=404, detail="site not found")
    report = InventoryReport.model_validate(payload.inventory)
    if report.site_name != site_name:
        raise HTTPException(status_code=422, detail="inventory site_name does not match route")
    return store.save_inventory(report).model_dump(mode="json")


@app.post("/sites/validate")
def validate_site(payload: SitePayload) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return {
        "valid": True,
        "site_name": spec.site.name,
        "platform": spec.platform.type.value,
        "hardware_provider": spec.hardware.vendor,
        "nodes": len(spec.hardware.nodes),
    }


@app.post("/sites/plan")
def plan_site(payload: SitePayload) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return Orchestrator().plan(spec).model_dump(mode="json")


@app.post("/sites/preflight")
def preflight_site(payload: SitePayload) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return PreflightRunner().run(spec).model_dump(mode="json")
