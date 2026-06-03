import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl

from strataone.artifacts import ArtifactGenerator
from strataone.inventory import InventoryReport
from strataone.jobs import JobRunner
from strataone.orchestrator import Orchestrator
from strataone.preflight import PreflightRunner
from strataone.providers.registry import ProviderInfo, delete_plugin_provider, list_providers, upsert_plugin_provider
from strataone.queue import queue_backend
from strataone.security import ALL_PERMISSIONS, AuthContext, auth_enabled, cors_origins, create_password_hash, new_session_token, require_permission, session_expiry, token_hash, verify_password, _bearer_token
from strataone.store import RoleRecord, StrataStore, UserRecord, spec_from_record
from strataone.state import SiteSpec, load_site_spec
from strataone.validation import validation_summary

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
    approval_id: str | None = None


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
    password: str | None = None


class LoginPayload(BaseModel):
    username: str
    password: str


class ProviderPayload(BaseModel):
    name: str
    type: str
    description: str
    vendor_supported: bool = False


class ProviderConfigPayload(BaseModel):
    config: dict[str, Any]


class ApprovalDecisionPayload(BaseModel):
    reason: str = ""


store = StrataStore()
jobs = JobRunner(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_admin_password()
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
read_audit = Depends(require_permission("read-audit", store))
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


@app.post("/auth/login")
def login(payload: LoginPayload) -> dict[str, Any]:
    user = store.get_user(payload.username.strip())
    password_hash = store.get_user_password_hash(payload.username.strip())
    if user is None or user.status != "active" or not verify_password(payload.password, password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    token = new_session_token()
    expires_at = session_expiry()
    store.create_session(token_hash(token), user.username, expires_at)
    store.add_audit(user.username, "auth.login", f"user:{user.username}", {"method": "password"})
    return {
        "token": token,
        "username": user.username,
        "display_name": user.display_name,
        "roles": user.roles,
        "expires_at": expires_at,
    }


@app.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    token = _bearer_token(authorization)
    if not token:
        return {"revoked": False}
    revoked = store.revoke_session(token_hash(token))
    store.add_audit("session", "auth.logout", "session", {"revoked": revoked})
    return {"revoked": revoked}


@app.get("/auth/sessions")
def list_sessions(_: Any = manage_access) -> dict[str, Any]:
    return {
        "sessions": [
            {
                "id": session.token_hash,
                "token_fingerprint": session.token_hash[:12],
                "username": session.username,
                "created_at": session.created_at,
                "expires_at": session.expires_at,
            }
            for session in store.list_sessions()
        ]
    }


@app.delete("/auth/sessions/{session_id}")
def revoke_session(session_id: str, context: AuthContext = Depends(require_permission("manage-access", store))) -> dict[str, bool]:
    revoked = store.revoke_session(session_id)
    store.add_audit(context.username, "session.revoke", f"session:{session_id[:12]}", {"revoked": revoked})
    return {"revoked": revoked}


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


def ensure_admin_password() -> None:
    password = os.getenv("STRATAONE_ADMIN_PASSWORD")
    admin = store.get_user("admin")
    if not password or admin is None or store.get_user_password_hash("admin"):
        return
    store.upsert_user(admin, password_hash=create_password_hash(password))


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
    result = upsert_plugin_provider(provider).model_dump(mode="json")
    store.add_audit("api", "provider.upsert", f"provider:{name}", result)
    return result


@app.delete("/providers/{provider_name}")
def delete_provider(provider_name: str, _: Any = manage_providers) -> dict[str, bool]:
    built_in = [provider for provider in list_providers() if provider.name == provider_name and not provider.editable]
    if built_in:
        raise HTTPException(status_code=409, detail="built-in providers cannot be deleted")
    deleted = delete_plugin_provider(provider_name)
    store.add_audit("api", "provider.delete", f"provider:{provider_name}", {"deleted": deleted})
    return {"deleted": deleted}


@app.get("/providers/{provider_name}")
def provider_detail(provider_name: str, _: Any = read_providers) -> dict[str, Any]:
    provider = next((item for item in list_providers() if item.name == provider_name), None)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    config = store.get_provider_config(provider_name)
    return {"provider": provider.model_dump(mode="json"), "config": config.model_dump(mode="json") if config else None}


@app.post("/providers/{provider_name}/config")
def save_provider_config(provider_name: str, payload: ProviderConfigPayload, _: Any = manage_providers) -> dict[str, Any]:
    if not any(item.name == provider_name for item in list_providers()):
        raise HTTPException(status_code=404, detail="provider not found")
    config = store.upsert_provider_config(provider_name, payload.config)
    store.add_audit("api", "provider.config.upsert", f"provider:{provider_name}", payload.config)
    return config.model_dump(mode="json")


@app.post("/providers/{provider_name}/test")
def test_provider(provider_name: str, context: AuthContext = Depends(require_permission("manage-providers", store))) -> dict[str, Any]:
    provider = next((item for item in list_providers() if item.name == provider_name), None)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    config = store.get_provider_config(provider_name)
    live_redfish = os.getenv("STRATAONE_ENABLE_LIVE_REDFISH", "false").lower() in {"1", "true", "yes", "on"}
    result = {
        "provider": provider_name,
        "type": provider.type,
        "status": "ready" if config else "configuration-required",
        "checks": [
            {"name": "provider_registered", "status": "passed"},
            {"name": "configuration_present", "status": "passed" if config else "warning"},
            {"name": "live_execution_enabled", "status": "passed" if live_redfish else "warning"},
        ],
    }
    store.add_audit(context.username, "provider.test", f"provider:{provider_name}", result)
    return result


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
            "mode": store.backend,
            "path": str(store.path) if store.backend == "sqlite" else store.postgres_dsn,
            "site_count": len(store.list_sites()),
            "job_count": len(store.list_jobs()),
            "execution_mode": os.getenv("STRATAONE_EXECUTION_MODE", "inline"),
            "queue_backend": queue_backend(),
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
            "enabled": True,
            "job_history_retention_days": int(os.getenv("STRATAONE_JOB_RETENTION_DAYS", "90")),
            "configuration_change_tracking": "enabled",
        },
        "validation": validation_summary(),
        "migrations": {
            "applied": [item.model_dump(mode="json") for item in store.list_migrations()],
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


@app.get("/validation/oem")
def oem_validation(_: Any = read_settings) -> dict[str, Any]:
    return validation_summary()


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
        password_configured=bool(payload.password),
        created_at="",
        updated_at="",
    )
    password_hash = create_password_hash(payload.password) if payload.password else None
    result = store.upsert_user(user, password_hash=password_hash).model_dump(mode="json")
    store.add_audit("api", "user.upsert", f"user:{user.username}", {"roles": user.roles, "status": user.status})
    return result


@app.delete("/access/users/{username}")
def delete_user(username: str, _: Any = manage_access) -> dict[str, bool]:
    deleted = store.delete_user(username)
    store.add_audit("api", "user.delete", f"user:{username}", {"deleted": deleted})
    return {"deleted": deleted}


@app.get("/sites")
def list_site_records(_: Any = read_sites) -> dict[str, Any]:
    return {"sites": [site.model_dump(mode="json") for site in store.list_sites()]}


@app.post("/sites")
def create_or_update_site(payload: SitePayload, _: Any = write_sites) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    result = store.upsert_site(spec).model_dump(mode="json")
    store.add_audit("api", "site.upsert", f"site:{spec.site.name}", {"platform": spec.platform.type.value})
    return result


@app.get("/sites/{site_name}")
def get_site_record(site_name: str, _: Any = read_sites) -> dict[str, Any]:
    site = store.get_site(site_name)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site.model_dump(mode="json")


@app.delete("/sites/{site_name}")
def delete_site_record(site_name: str, _: Any = delete_sites) -> dict[str, bool]:
    deleted = store.delete_site(site_name)
    store.add_audit("api", "site.delete", f"site:{site_name}", {"deleted": deleted})
    return {"deleted": deleted}


@app.post("/sites/{site_name}/jobs/{action}")
def run_site_job(site_name: str, action: str, payload: JobPayload | None = None, authorization: str | None = Header(default=None)) -> dict[str, str]:
    if action not in {"validate", "plan", "inventory", "preflight", "artifacts", "mount-iso", "deploy-azure-local", "drift-detect", "node-replacement"}:
        raise HTTPException(status_code=400, detail="unsupported action")
    if store.get_site(site_name) is None:
        raise HTTPException(status_code=404, detail="site not found")
    context = require_permission(_permission_for_action(action), store)(authorization)
    params = payload.model_dump(mode="json", exclude_none=True) if payload else {}
    if _approval_required(action, params):
        approval_id = params.get("approval_id")
        approval = store.get_approval(approval_id) if approval_id else None
        if approval is None or approval.status != "approved":
            pending = store.create_approval(site_name, action, context.username, {"params": _approval_safe_params(params)})
            store.add_audit(context.username, "approval.requested", f"approval:{pending.id}", {"site": site_name, "action": action})
            return {"approval_id": pending.id, "status": "approval-required"}
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


@app.get("/jobs/{job_id}/events")
def get_job_events(job_id: str, _: Any = read_jobs) -> dict[str, Any]:
    return {"events": [event.model_dump(mode="json") for event in store.list_job_events(job_id)]}


@app.get("/jobs/{job_id}/events/stream")
def stream_job_events(job_id: str, _: Any = read_jobs) -> StreamingResponse:
    def event_stream():
        seen: set[str] = set()
        for _ in range(120):
            events = store.list_job_events(job_id)
            for event in events:
                if event.id in seen:
                    continue
                seen.add(event.id)
                yield f"event: job-event\ndata: {event.model_dump_json()}\n\n"
            job = store.get_job(job_id)
            if job and job.status in {"succeeded", "failed"} and all(event.id in seen for event in events):
                break
            time.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/audit")
def list_audit_log(limit: int = 100, _: Any = read_audit) -> dict[str, Any]:
    return {"audit": [item.model_dump(mode="json") for item in store.list_audit(limit)]}


@app.get("/approvals")
def list_approval_records(_: Any = read_jobs) -> dict[str, Any]:
    return {"approvals": [item.model_dump(mode="json") for item in store.list_approvals()]}


@app.post("/approvals/{approval_id}/approve")
def approve_request(approval_id: str, context: AuthContext = Depends(require_permission("manage-settings", store))) -> dict[str, Any]:
    approval = store.approve(approval_id, context.username)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    store.add_audit(context.username, "approval.approved", f"approval:{approval_id}", approval.model_dump(mode="json"))
    return approval.model_dump(mode="json")


@app.post("/approvals/{approval_id}/reject")
def reject_request(approval_id: str, payload: ApprovalDecisionPayload | None = None, context: AuthContext = Depends(require_permission("manage-settings", store))) -> dict[str, Any]:
    approval = store.reject(approval_id, context.username, payload.reason if payload else "")
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    store.add_audit(context.username, "approval.rejected", f"approval:{approval_id}", approval.model_dump(mode="json"))
    return approval.model_dump(mode="json")


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
        "deploy-azure-local": "run-plan",
        "drift-detect": "run-preflight",
        "node-replacement": "run-preflight",
    }[action]


def _approval_required(action: str, params: dict[str, Any]) -> bool:
    if not os.getenv("STRATAONE_REQUIRE_APPROVALS", "true").lower() in {"1", "true", "yes", "on"}:
        return False
    return action in {"mount-iso", "deploy-azure-local", "node-replacement"}


def _approval_safe_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: ("***" if key in {"password", "username"} else value) for key, value in params.items()}
