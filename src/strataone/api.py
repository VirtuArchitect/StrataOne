import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from strataone.artifacts import ArtifactGenerator
from strataone.inventory import InventoryReport
from strataone.jobs import JobRunner
from strataone.orchestrator import Orchestrator
from strataone.preflight import PreflightRunner
from strataone.providers.registry import ProviderInfo, delete_plugin_provider, list_providers, upsert_plugin_provider
from strataone.security import ALL_PERMISSIONS, auth_enabled, cors_origins, require_permission
from strataone.store import RoleRecord, StrataStore, UserRecord, spec_from_record
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
    iso_url: HttpUrl | None = None
    boot_once: bool | None = None


class RolePayload(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = []


class UserPayload(BaseModel):
    username: str
    display_name: str
    email: str
    roles: list[str] = []
    status: str = "active"


class ProviderPayload(BaseModel):
    name: str
    type: str
    description: str
    vendor_supported: bool = False


store = StrataStore()
jobs = JobRunner(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("STRATAONE_SEED_EXAMPLE", "true").lower() in {"1", "true", "yes"}:
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
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _spec_from_payload(payload: SitePayload) -> SiteSpec:
    try:
        return SiteSpec.model_validate(payload.site)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


read_sites = Depends(require_permission("read-sites", store))
write_sites = Depends(require_permission("create-sites", store))
delete_sites = Depends(require_permission("delete-sites", store))
read_jobs = Depends(require_permission("read-jobs", store))
read_inventory = Depends(require_permission("read-inventory", store))
write_inventory = Depends(require_permission("write-inventory", store))
read_providers = Depends(require_permission("read-providers", store))
manage_providers = Depends(require_permission("manage-providers", store))
read_settings = Depends(require_permission("read-settings", store))
manage_access = Depends(require_permission("manage-access", store))
worker_execute = Depends(require_permission("worker-execute", store))


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
def example_site(_: Any = read_sites) -> dict[str, Any]:
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
def providers(_: Any = read_providers) -> dict[str, Any]:
    return {"providers": [provider.model_dump(mode="json") for provider in list_providers()]}


@app.post("/providers")
def create_or_update_provider(payload: ProviderPayload, _: Any = manage_providers) -> dict[str, Any]:
    if payload.type not in {"hardware", "platform"}:
        raise HTTPException(status_code=422, detail="provider type must be hardware or platform")
    name = payload.name.strip().lower().replace(" ", "-")
    if not name:
        raise HTTPException(status_code=422, detail="provider name is required")
    built_in = [provider for provider in list_providers() if provider.name == name and not provider.editable]
    if built_in:
        raise HTTPException(status_code=409, detail="built-in providers cannot be modified")
    provider = ProviderInfo(
        name=name,
        type=payload.type,
        source="plugins",
        description=payload.description.strip() or "Custom StrataOne provider",
        vendor_supported=payload.vendor_supported,
        editable=True,
    )
    return upsert_plugin_provider(provider).model_dump(mode="json")


@app.delete("/providers/{provider_name}")
def delete_provider(provider_name: str, _: Any = manage_providers) -> dict[str, bool]:
    built_in = [provider for provider in list_providers() if provider.name == provider_name and not provider.editable]
    if built_in:
        raise HTTPException(status_code=409, detail="built-in providers cannot be deleted")
    return {"deleted": delete_plugin_provider(provider_name)}


@app.get("/settings")
def settings(_: Any = read_settings) -> dict[str, Any]:
    provider_list = list_providers()
    return {
        "general": {
            "instance_name": os.getenv("STRATAONE_INSTANCE_NAME", "StrataOne"),
            "environment": os.getenv("STRATAONE_ENVIRONMENT", "development"),
            "api_port": os.getenv("STRATAONE_API_PORT", "8080"),
            "dashboard_port": os.getenv("STRATAONE_DASHBOARD_PORT", "8088"),
        },
        "access": {
            "mode": "rbac" if auth_enabled() else "local-dev",
            "rbac_enforced": auth_enabled(),
            "permissions": sorted(ALL_PERMISSIONS),
            "oidc_enabled": bool(os.getenv("STRATAONE_OIDC_ISSUER")),
            "users": [user.model_dump(mode="json") for user in store.list_users()],
            "roles": [role.model_dump(mode="json") for role in store.list_roles()],
        },
        "secrets": {
            "bmc_username_configured": bool(os.getenv("STRATAONE_BMC_USERNAME")),
            "bmc_password_configured": bool(os.getenv("STRATAONE_BMC_PASSWORD")),
            "dashboard_transient_credentials": True,
            "vault_provider": os.getenv("STRATAONE_VAULT_PROVIDER", "env"),
            "vault_file_configured": bool(os.getenv("STRATAONE_VAULT_FILE")),
            "hashicorp_vault_configured": bool(os.getenv("STRATAONE_VAULT_ADDR")),
        },
        "database": {
            "mode": "sqlite",
            "path": str(store.path),
            "site_count": len(store.list_sites()),
            "job_count": len(store.list_jobs()),
            "execution_mode": os.getenv("STRATAONE_EXECUTION_MODE", "inline"),
        },
        "providers": {
            "plugin_dir": os.getenv("STRATAONE_PLUGIN_DIR", "plugins"),
            "hardware": [provider.model_dump(mode="json") for provider in provider_list if provider.type == "hardware"],
            "platform": [provider.model_dump(mode="json") for provider in provider_list if provider.type == "platform"],
        },
        "api": {
            "cors": os.getenv("STRATAONE_CORS_ORIGINS", "http://localhost:8088,http://127.0.0.1:8088"),
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


@app.get("/access/roles")
def list_roles(_: Any = manage_access) -> dict[str, Any]:
    return {"roles": [role.model_dump(mode="json") for role in store.list_roles()]}


@app.post("/access/roles")
def create_or_update_role(payload: RolePayload, _: Any = manage_access) -> dict[str, Any]:
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="role name is required")
    role = RoleRecord(
        name=payload.name.strip(),
        description=payload.description.strip() or "Custom StrataOne role",
        permissions=[permission.strip() for permission in payload.permissions if permission.strip()],
        built_in=False,
        created_at="",
        updated_at="",
    )
    return store.upsert_role(role).model_dump(mode="json")


@app.delete("/access/roles/{role_name}")
def delete_role(role_name: str, _: Any = manage_access) -> dict[str, bool]:
    deleted = store.delete_role(role_name)
    if not deleted:
        role = store.get_role(role_name)
        if role and role.built_in:
            raise HTTPException(status_code=409, detail="built-in roles cannot be deleted")
    return {"deleted": deleted}


@app.get("/access/users")
def list_users(_: Any = manage_access) -> dict[str, Any]:
    return {"users": [user.model_dump(mode="json") for user in store.list_users()]}


@app.post("/access/users")
def create_or_update_user(payload: UserPayload, _: Any = manage_access) -> dict[str, Any]:
    if not payload.username.strip():
        raise HTTPException(status_code=422, detail="username is required")
    known_roles = {role.name for role in store.list_roles()}
    unknown_roles = [role for role in payload.roles if role not in known_roles]
    if unknown_roles:
        raise HTTPException(status_code=422, detail=f"unknown roles: {', '.join(unknown_roles)}")
    user = UserRecord(
        username=payload.username.strip(),
        display_name=payload.display_name.strip() or payload.username.strip(),
        email=payload.email.strip(),
        roles=payload.roles,
        status=payload.status,
        created_at="",
        updated_at="",
    )
    return store.upsert_user(user).model_dump(mode="json")


@app.delete("/access/users/{username}")
def delete_user(username: str, _: Any = manage_access) -> dict[str, bool]:
    return {"deleted": store.delete_user(username)}


@app.get("/sites")
def list_site_records(_: Any = read_sites) -> dict[str, Any]:
    return {"sites": [site.model_dump(mode="json") for site in store.list_sites()]}


@app.post("/sites")
def create_or_update_site(payload: SitePayload, _: Any = write_sites) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return store.upsert_site(spec).model_dump(mode="json")


@app.get("/sites/{site_name}")
def get_site_record(site_name: str, _: Any = read_sites) -> dict[str, Any]:
    site = store.get_site(site_name)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site.model_dump(mode="json")


@app.delete("/sites/{site_name}")
def delete_site_record(site_name: str, _: Any = delete_sites) -> dict[str, bool]:
    return {"deleted": store.delete_site(site_name)}


@app.post("/sites/{site_name}/jobs/{action}")
def run_site_job(site_name: str, action: str, payload: JobPayload | None = None, authorization: str | None = Header(default=None)) -> dict[str, str]:
    if action not in {"validate", "plan", "inventory", "preflight", "artifacts", "mount-iso"}:
        raise HTTPException(status_code=400, detail="unsupported action")
    if store.get_site(site_name) is None:
        raise HTTPException(status_code=404, detail="site not found")
    require_permission(_permission_for_action(action), store)(authorization)
    params = payload.model_dump(mode="json", exclude_none=True) if payload else {}
    return {"job_id": jobs.submit(site_name, action, params)}


@app.get("/jobs")
def list_job_records(site_name: str | None = None, _: Any = read_jobs) -> dict[str, Any]:
    return {"jobs": [job.model_dump(mode="json") for job in store.list_jobs(site_name)]}


@app.get("/jobs/{job_id}")
def get_job_record(job_id: str, _: Any = read_jobs) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump(mode="json")


@app.post("/sites/{site_name}/artifacts")
def generate_artifacts(site_name: str, _: Any = Depends(require_permission("generate-artifacts", store))) -> dict[str, Any]:
    site = store.get_site(site_name)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return ArtifactGenerator().generate(spec_from_record(site)).model_dump(mode="json")


@app.get("/sites/{site_name}/inventory")
def get_site_inventory(site_name: str, _: Any = read_inventory) -> dict[str, Any]:
    inventory = store.get_inventory(site_name)
    if inventory is None:
        raise HTTPException(status_code=404, detail="inventory not found")
    return inventory.model_dump(mode="json")


@app.post("/sites/{site_name}/inventory")
def save_site_inventory(site_name: str, payload: InventoryPayload, _: Any = write_inventory) -> dict[str, Any]:
    if store.get_site(site_name) is None:
        raise HTTPException(status_code=404, detail="site not found")
    report = InventoryReport.model_validate(payload.inventory)
    if report.site_name != site_name:
        raise HTTPException(status_code=422, detail="inventory site_name does not match route")
    return store.save_inventory(report).model_dump(mode="json")


@app.post("/sites/validate")
def validate_site(payload: SitePayload, _: Any = Depends(require_permission("run-validate", store))) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return {
        "valid": True,
        "site_name": spec.site.name,
        "platform": spec.platform.type.value,
        "hardware_provider": spec.hardware.vendor,
        "nodes": len(spec.hardware.nodes),
    }


@app.post("/sites/plan")
def plan_site(payload: SitePayload, _: Any = Depends(require_permission("run-plan", store))) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return Orchestrator().plan(spec).model_dump(mode="json")


@app.post("/sites/preflight")
def preflight_site(payload: SitePayload, _: Any = Depends(require_permission("run-preflight", store))) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    return PreflightRunner().run(spec).model_dump(mode="json")


@app.post("/jobs/worker/run-once")
def run_queued_job_once(_: Any = worker_execute) -> dict[str, Any]:
    job_id = jobs.run_queued_once()
    return {"job_id": job_id, "ran": job_id is not None}


def _permission_for_action(action: str) -> str:
    return {
        "validate": "run-validate",
        "plan": "run-plan",
        "inventory": "run-inventory",
        "preflight": "run-preflight",
        "artifacts": "generate-artifacts",
        "mount-iso": "mount-iso",
    }[action]
