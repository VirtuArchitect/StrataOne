import os
import time
import io
import json
import zipfile
import socket
from ipaddress import ip_address, ip_network
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
import requests

from strataone import __version__
from strataone.artifacts import ArtifactGenerator
from strataone.inventory import InventoryReport
from strataone.jobs import JobRunner
from strataone.orchestrator import Orchestrator
from strataone.preflight import PreflightRunner
from strataone.providers.registry import ProviderInfo, delete_plugin_provider, list_providers, upsert_plugin_provider
from strataone.queue import queue_backend
from strataone.redfish import RedfishClient
from strataone.security import ALL_PERMISSIONS, AuthContext, RateLimitMiddleware, SecurityHeadersMiddleware, authenticate, auth_enabled, cors_origins, create_password_hash, new_session_token, rate_limit_enabled, require_permission, security_headers, session_expiry, token_hash, verify_password, _bearer_token
from strataone.secrets import BmcSecret, resolve_bmc_credentials_from_ref
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
    credential_ref: str | None = None
    insecure: bool | None = None
    timeout: float | None = None
    iso_url: HttpUrl | None = None
    iso_ref: str | None = None
    boot_once: bool | None = None
    approval_id: str | None = None


class RolePayload(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = []


class UserPayload(BaseModel):
    username: str
    tenant_id: str = "default"
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


class ProviderValidationPayload(BaseModel):
    operation: str
    status: str = "validated"
    lab: str | None = None
    evidence: str | None = None
    notes: str | None = None


class ProviderHarnessPayload(BaseModel):
    operation: str = "connectivity"
    target: str | None = None
    credential_ref: str | None = None
    live: bool = False
    timeout: float = 5


class SecretRefPayload(BaseModel):
    name: str
    type: str = "bmc"
    provider: str = "file"
    reference: str
    metadata: dict[str, Any] = {}


class DiscoveryPayload(BaseModel):
    name: str = "BMC discovery"
    cidr: str
    provider: str = "generic-redfish"
    credential_ref: str | None = None


class DiscoveryImportPayload(BaseModel):
    site_name: str
    location: str = "discovered"
    deployment_model: str = "edge-hci"
    platform: str = "azure-local"
    selected_bmc_ips: list[str] = []
    azure_subscription_id: str = "00000000-0000-0000-0000-000000000000"
    azure_tenant_id: str = "00000000-0000-0000-0000-000000000000"
    azure_resource_group: str | None = None
    azure_region: str = "westeurope"


class IsoPayload(BaseModel):
    name: str
    uri: HttpUrl
    checksum: str | None = None
    checksum_algorithm: str = "sha256"


class ApprovalPolicyPayload(BaseModel):
    action: str
    enabled: bool = True
    approver_roles: list[str] = []
    min_approvals: int = 1
    expires_minutes: int = 1440


class ApprovalDecisionPayload(BaseModel):
    reason: str = ""


class ArtifactFileRecord(BaseModel):
    name: str
    path: str
    size_bytes: int
    updated_at: str


class NotificationTestPayload(BaseModel):
    type: str
    name: str = "default"
    target: str
    enabled: bool = True
    send: bool = False
    message: str = "StrataOne notification test"


class GitOpsExportPayload(BaseModel):
    site_name: str
    format: str = "yaml"
    repository: str | None = None
    branch: str = "main"
    path: str | None = None


class GitOpsImportPayload(BaseModel):
    content: str | None = None
    site: dict[str, Any] | None = None
    source: str = "dashboard"


store = StrataStore()
jobs = JobRunner(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_secure_runtime_defaults()
    ensure_admin_password()
    if os.getenv("STRATAONE_SEED_EXAMPLE", "true").lower() in {"1", "true", "yes"}:
        seed_example_site()
    yield


app = FastAPI(
    title="StrataOne API",
    version=__version__,
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
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)


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
manage_settings = Depends(require_permission("manage-settings", store))
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


def validate_secure_runtime_defaults() -> None:
    environment = os.getenv("STRATAONE_ENVIRONMENT", "development").lower()
    if environment not in {"prod", "production"}:
        return
    insecure_values = {
        "STRATAONE_BOOTSTRAP_TOKEN": {"", "change-this-token"},
        "STRATAONE_ADMIN_PASSWORD": {"", "change-this-password"},
        "POSTGRES_PASSWORD": {"", "strataone"},
    }
    failures = [
        name
        for name, blocked in insecure_values.items()
        if os.getenv(name, "") in blocked
    ]
    if failures:
        raise RuntimeError(f"production startup blocked by insecure default setting(s): {', '.join(failures)}")


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
    return {
        "provider": provider.model_dump(mode="json"),
        "config": config.model_dump(mode="json") if config else None,
        "template": _provider_config_template(provider.name, provider.type),
        "validation": [item.model_dump(mode="json") for item in store.list_provider_validation(provider_name)],
        "validation_runs": [item.model_dump(mode="json") for item in store.list_provider_validation_runs(provider_name)],
    }


@app.post("/providers/{provider_name}/config")
def save_provider_config(provider_name: str, payload: ProviderConfigPayload, _: Any = manage_providers) -> dict[str, Any]:
    if not any(item.name == provider_name for item in list_providers()):
        raise HTTPException(status_code=404, detail="provider not found")
    config = store.upsert_provider_config(provider_name, payload.config)
    store.add_audit("api", "provider.config.upsert", f"provider:{provider_name}", _redact_sensitive(payload.config))
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


@app.post("/providers/{provider_name}/validation")
def add_provider_validation(provider_name: str, payload: ProviderValidationPayload, context: AuthContext = manage_providers) -> dict[str, Any]:
    if not any(item.name == provider_name for item in list_providers()):
        raise HTTPException(status_code=404, detail="provider not found")
    if payload.status not in {"validated", "failed", "pending", "not-validated"}:
        raise HTTPException(status_code=422, detail="unsupported validation status")
    record = store.add_provider_validation(provider_name, payload.operation, payload.status, payload.lab, payload.evidence, payload.notes)
    store.add_audit(context.username, "provider.validation.add", f"provider:{provider_name}", record.model_dump(mode="json"))
    return record.model_dump(mode="json")


@app.post("/providers/{provider_name}/validation/run")
def run_provider_validation_harness(provider_name: str, payload: ProviderHarnessPayload, context: AuthContext = Depends(require_permission("manage-providers", store))) -> dict[str, Any]:
    provider = next((item for item in list_providers() if item.name == provider_name), None)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    live_allowed = os.getenv("STRATAONE_ENABLE_LIVE_REDFISH", "false").lower() in {"1", "true", "yes", "on"}
    if payload.live and not live_allowed:
        raise HTTPException(status_code=409, detail="live provider validation is disabled")
    result = _provider_harness_result(provider, payload)
    record = store.create_provider_validation_run(provider_name, payload.operation, result["mode"], result["status"], payload.target, result)
    if result["status"] == "passed":
        store.add_provider_validation(provider_name, payload.operation, "validated", "harness", record.id, result.get("summary"))
    store.add_audit(context.username, "provider.validation.run", f"provider:{provider_name}", record.model_dump(mode="json"))
    return record.model_dump(mode="json")


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
            "tenant_enforced": os.getenv("STRATAONE_TENANT_ENFORCEMENT", "true").lower() in {"1", "true", "yes", "on"},
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
            "refs": [item.model_dump(mode="json") for item in store.list_secret_refs()],
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
            "configured": [item.provider_name for item in [store.get_provider_config(provider.name) for provider in provider_list] if item],
            "validation": [item.model_dump(mode="json") for item in store.list_provider_validation()],
        },
        "api": {
            "cors": os.getenv("STRATAONE_CORS_ORIGINS", "http://localhost:8088,http://127.0.0.1:8088"),
            "docs": "/docs",
            "health": "/health",
            "session_timeout_minutes": int(os.getenv("STRATAONE_SESSION_TIMEOUT_MINUTES", "60")),
            "rate_limit_enabled": rate_limit_enabled(),
            "rate_limit_requests": int(os.getenv("STRATAONE_RATE_LIMIT_REQUESTS", "120")),
            "rate_limit_window_seconds": int(os.getenv("STRATAONE_RATE_LIMIT_WINDOW_SECONDS", "60")),
            "security_headers": security_headers(),
            "approval_required_actions": sorted(_approval_required_actions()),
            "approval_policies": [item.model_dump(mode="json") for item in store.list_approval_policies()],
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
        "discovery": {
            "runs": [item.model_dump(mode="json") for item in store.list_discovery_runs()],
            "max_candidates": int(os.getenv("STRATAONE_DISCOVERY_MAX_CANDIDATES", "32")),
        },
        "migrations": {
            "applied": [item.model_dump(mode="json") for item in store.list_migrations()],
        },
    }


@app.get("/secrets")
def list_secret_refs(_: Any = read_settings) -> dict[str, Any]:
    return {"secrets": [item.model_dump(mode="json") for item in store.list_secret_refs()]}


@app.post("/secrets")
def save_secret_ref(payload: SecretRefPayload, context: AuthContext = manage_settings) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="secret name is required")
    if payload.provider not in {"env", "file", "vault", "hashicorp-vault"}:
        raise HTTPException(status_code=422, detail="secret provider must be env, file, vault, or hashicorp-vault")
    record = store.upsert_secret_ref(name, payload.type.strip() or "generic", payload.provider, payload.reference.strip(), payload.metadata)
    store.add_audit(context.username, "secret.ref.upsert", f"secret:{name}", _redact_secret(record.model_dump(mode="json")))
    return record.model_dump(mode="json")


@app.delete("/secrets/{secret_name}")
def delete_secret_ref(secret_name: str, context: AuthContext = manage_settings) -> dict[str, bool]:
    deleted = store.delete_secret_ref(secret_name)
    store.add_audit(context.username, "secret.ref.delete", f"secret:{secret_name}", {"deleted": deleted})
    return {"deleted": deleted}


@app.post("/secrets/{secret_name}/test")
def test_secret_ref(secret_name: str, context: AuthContext = manage_settings) -> dict[str, Any]:
    secret = store.get_secret_ref(secret_name)
    if secret is None:
        raise HTTPException(status_code=404, detail="secret reference not found")
    resolved = resolve_bmc_credentials_from_ref(secret)
    result = {
        "name": secret.name,
        "type": secret.type,
        "provider": secret.provider,
        "resolved": resolved is not None,
        "status": "resolved" if resolved else "unresolved",
    }
    store.add_audit(context.username, "secret.ref.test", f"secret:{secret_name}", result)
    return result


@app.get("/discovery")
def list_discovery(_: Any = read_sites) -> dict[str, Any]:
    return {"runs": [item.model_dump(mode="json") for item in store.list_discovery_runs()]}


@app.post("/discovery")
def create_discovery(payload: DiscoveryPayload, context: AuthContext = Depends(require_permission("run-inventory", store))) -> dict[str, Any]:
    provider = next((item for item in list_providers() if item.name == payload.provider), None)
    if provider is None or provider.type != "hardware":
        raise HTTPException(status_code=422, detail="discovery provider must be a known hardware provider")
    try:
        network = ip_network(payload.cidr, strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="cidr must be a valid IP network") from exc
    max_candidates = int(os.getenv("STRATAONE_DISCOVERY_MAX_CANDIDATES", "32"))
    candidates = [str(address) for index, address in enumerate(network.hosts()) if index < max_candidates]
    result = {
        "mode": "planned",
        "provider": provider.name,
        "credential_ref": payload.credential_ref,
        "candidate_count": len(candidates),
        "candidates": [{"bmc_ip": address, "status": "pending-scan"} for address in candidates],
        "next_actions": ["Run Redfish reachability scan", "Classify reachable systems", "Import selected nodes into a deployment"],
    }
    record = store.create_discovery_run(payload.name.strip() or "BMC discovery", str(network), provider.name, result)
    store.add_audit(context.username, "discovery.plan", f"discovery:{record.id}", {"cidr": str(network), "provider": provider.name})
    return record.model_dump(mode="json")


@app.post("/discovery/{run_id}/execute")
def execute_discovery(run_id: str, context: AuthContext = Depends(require_permission("run-inventory", store))) -> dict[str, Any]:
    run = store.get_discovery_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="discovery run not found")
    live = os.getenv("STRATAONE_ENABLE_LIVE_REDFISH", "false").lower() in {"1", "true", "yes", "on"}
    credential_ref = run.result.get("credential_ref")
    secret = store.get_secret_ref(credential_ref) if credential_ref else None
    credentials = resolve_bmc_credentials_from_ref(secret) or BmcSecret(username="", password="")
    client = RedfishClient(credentials, timeout=float(os.getenv("STRATAONE_DISCOVERY_TIMEOUT", "5")), verify_tls=False)
    scanned = []
    for candidate in run.result.get("candidates", []):
        bmc_ip = candidate.get("bmc_ip")
        if live:
            scanned.append(client.probe_service_root(str(bmc_ip)))
        else:
            scanned.append({**candidate, "status": "scan-ready", "reachable": None})
    result = {
        **run.result,
        "mode": "live-redfish" if live else "planned",
        "candidates": scanned,
        "scanned_count": len(scanned),
    }
    status = "completed" if live else "ready-for-live-scan"
    updated = store.update_discovery_run(run_id, status, result)
    store.add_audit(context.username, "discovery.execute", f"discovery:{run_id}", {"status": status, "live": live})
    return updated.model_dump(mode="json") if updated else run.model_dump(mode="json")


@app.delete("/discovery/{run_id}")
def delete_discovery(run_id: str, context: AuthContext = Depends(require_permission("run-inventory", store))) -> dict[str, bool]:
    deleted = store.delete_discovery_run(run_id)
    store.add_audit(context.username, "discovery.delete", f"discovery:{run_id}", {"deleted": deleted})
    return {"deleted": deleted}


@app.post("/discovery/{run_id}/import")
def import_discovery(run_id: str, payload: DiscoveryImportPayload, context: AuthContext = Depends(require_permission("create-sites", store))) -> dict[str, Any]:
    run = store.get_discovery_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="discovery run not found")
    selected = set(payload.selected_bmc_ips)
    candidates = [
        candidate for candidate in run.result.get("candidates", [])
        if not selected or candidate.get("bmc_ip") in selected
    ]
    if not candidates:
        raise HTTPException(status_code=422, detail="no discovery candidates selected")
    nodes = [
        {
            "serial": _candidate_serial(candidate, index),
            "bmc_ip": candidate["bmc_ip"],
            "role": "host",
        }
        for index, candidate in enumerate(candidates, start=1)
        if candidate.get("bmc_ip")
    ]
    spec = SiteSpec.model_validate(
        {
            "site": {
                "name": payload.site_name.strip(),
                "location": payload.location,
                "deployment_model": payload.deployment_model,
            },
            "hardware": {"vendor": run.provider, "nodes": nodes},
            "network": {"management_vlan": 100, "storage_vlan": 110, "vm_vlan": 120, "dns_servers": [], "ntp_servers": []},
            "platform": {
                "type": payload.platform,
                "topology": "discovered",
                "cluster_name": payload.site_name.strip(),
                "azure": {
                    "subscription_id": payload.azure_subscription_id,
                    "tenant_id": payload.azure_tenant_id,
                    "resource_group": payload.azure_resource_group or f"rg-{payload.site_name.strip()}",
                    "region": payload.azure_region,
                },
            },
            "workloads": {},
        }
    )
    site = store.upsert_site(spec)
    store.add_audit(context.username, "discovery.import", f"site:{site.name}", {"discovery_id": run_id, "nodes": len(nodes)})
    return site.model_dump(mode="json")


@app.get("/isos")
def list_isos(_: Any = read_sites) -> dict[str, Any]:
    return {"isos": [item.model_dump(mode="json") for item in store.list_isos()]}


@app.get("/isos/browse")
def browse_isos(_: Any = read_sites) -> dict[str, Any]:
    library_dir = Path(os.getenv("STRATAONE_ISO_LIBRARY_DIR", ".strataone/iso-library")).resolve()
    url_prefix = os.getenv("STRATAONE_ISO_LIBRARY_URL_PREFIX", "").rstrip("/")
    entries: list[dict[str, Any]] = []
    if library_dir.exists() and library_dir.is_dir():
        for path in sorted(library_dir.glob("*.iso")):
            stat = path.stat()
            uri = f"{url_prefix}/{path.name}" if url_prefix else ""
            entries.append(
                {
                    "name": path.stem,
                    "filename": path.name,
                    "uri": uri,
                    "size_bytes": stat.st_size,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                    "registerable": bool(uri),
                }
            )
    return {
        "directory": str(library_dir),
        "url_prefix": url_prefix,
        "isos": entries,
    }


@app.post("/isos")
def save_iso(payload: IsoPayload, context: AuthContext = Depends(require_permission("generate-artifacts", store))) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="iso name is required")
    record = store.upsert_iso(name, str(payload.uri), payload.checksum, payload.checksum_algorithm)
    store.add_audit(context.username, "iso.upsert", f"iso:{name}", {"uri": record.uri, "checksum": bool(record.checksum)})
    return record.model_dump(mode="json")


@app.delete("/isos/{iso_name}")
def delete_iso(iso_name: str, context: AuthContext = Depends(require_permission("generate-artifacts", store))) -> dict[str, bool]:
    deleted = store.delete_iso(iso_name)
    store.add_audit(context.username, "iso.delete", f"iso:{iso_name}", {"deleted": deleted})
    return {"deleted": deleted}


@app.post("/isos/{iso_name}/validate")
def validate_iso(iso_name: str, context: AuthContext = Depends(require_permission("generate-artifacts", store))) -> dict[str, Any]:
    iso = store.get_iso(iso_name)
    if iso is None:
        raise HTTPException(status_code=404, detail="iso not found")
    _assert_safe_outbound_url(iso.uri)
    try:
        response = _safe_outbound_request("head", iso.uri, timeout=float(os.getenv("STRATAONE_ISO_VALIDATE_TIMEOUT", "5")))
        reachable = response.status_code < 400
        content_length = response.headers.get("Content-Length")
        status = "validated" if reachable else "unreachable"
    except HTTPException:
        raise
    except Exception as exc:
        reachable = False
        content_length = None
        status = "unreachable"
        error = str(exc)
    else:
        error = None
    updated = store.update_iso_status(iso_name, status)
    result = {
        "name": iso.name,
        "uri": iso.uri,
        "reachable": reachable,
        "status": status,
        "checksum_registered": bool(iso.checksum),
        "content_length": content_length,
        "error": error,
        "record": updated.model_dump(mode="json") if updated else iso.model_dump(mode="json"),
    }
    store.add_audit(context.username, "iso.validate", f"iso:{iso_name}", {"status": status, "reachable": reachable})
    return result


@app.get("/approval-policy")
def list_approval_policy(_: Any = read_settings) -> dict[str, Any]:
    return {"policies": [item.model_dump(mode="json") for item in store.list_approval_policies()]}


@app.post("/approval-policy")
def save_approval_policy(payload: ApprovalPolicyPayload, context: AuthContext = manage_settings) -> dict[str, Any]:
    action = payload.action.strip()
    if not action:
        raise HTTPException(status_code=422, detail="action is required")
    policy = store.upsert_approval_policy(
        action,
        enabled=payload.enabled,
        approver_roles=payload.approver_roles,
        min_approvals=payload.min_approvals,
        expires_minutes=payload.expires_minutes,
    )
    store.add_audit(context.username, "approval.policy.upsert", f"approval-policy:{policy.id}", policy.model_dump(mode="json"))
    return policy.model_dump(mode="json")


@app.delete("/approval-policy/{policy_id}")
def delete_approval_policy(policy_id: str, context: AuthContext = manage_settings) -> dict[str, bool]:
    deleted = store.delete_approval_policy(policy_id)
    store.add_audit(context.username, "approval.policy.delete", f"approval-policy:{policy_id}", {"deleted": deleted})
    return {"deleted": deleted}


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


@app.get("/templates")
def deployment_templates() -> dict[str, Any]:
    return {"templates": _deployment_templates()}


@app.get("/compatibility")
def compatibility_matrix(_: Any = read_providers) -> dict[str, Any]:
    providers = list_providers()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "hardware": [_compatibility_record(provider) for provider in providers if provider.type == "hardware"],
        "platform": [_compatibility_record(provider) for provider in providers if provider.type == "platform"],
        "certifications": [
            {"name": "StrataOne built-in", "meaning": "Provider contract ships with the product."},
            {"name": "Vendor supported", "meaning": "Provider is aligned to a named vendor/OEM integration path."},
            {"name": "Lab validated", "meaning": "Live execution evidence has been recorded for one or more operations."},
            {"name": "Approval gated", "meaning": "Live-impact actions require an approved request before execution."},
        ],
    }


@app.get("/releases")
def releases(_: Any = read_sites) -> dict[str, Any]:
    return {"releases": _release_notes()}


@app.post("/notifications/test")
def test_notification(payload: NotificationTestPayload, context: AuthContext = manage_settings) -> dict[str, Any]:
    if payload.type not in {"teams", "slack", "email", "webhook"}:
        raise HTTPException(status_code=422, detail="notification type must be teams, slack, email, or webhook")
    if payload.type in {"teams", "slack", "webhook"}:
        _assert_safe_outbound_url(payload.target)
    result = {
        "name": payload.name.strip() or payload.type,
        "type": payload.type,
        "target": _redact_notification_target(payload.target),
        "enabled": payload.enabled,
        "mode": "sent" if payload.send else "validated",
        "status": "ready",
        "message": payload.message,
    }
    if payload.send:
        if payload.type in {"teams", "slack", "webhook"}:
            try:
                response = _safe_outbound_request("post", payload.target, json={"text": payload.message, "source": "StrataOne"}, timeout=5)
                result["http_status"] = response.status_code
                result["status"] = "sent" if response.status_code < 400 else "failed"
            except HTTPException:
                raise
            except Exception as exc:
                result["status"] = "failed"
                result["error"] = str(exc)
        else:
            result["status"] = "planned"
            result["note"] = "SMTP delivery is configured as an operator integration contract."
    store.add_audit(context.username, "notification.test", f"notification:{payload.type}:{payload.name}", result)
    return result


@app.post("/gitops/export")
def gitops_export(payload: GitOpsExportPayload, context: AuthContext = read_sites) -> dict[str, Any]:
    site = store.get_site(payload.site_name, _tenant_scope(context))
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    spec = spec_from_record(site).model_dump(mode="json")
    if payload.format not in {"yaml", "json"}:
        raise HTTPException(status_code=422, detail="format must be yaml or json")
    file_name = f"{site.name}.{'yaml' if payload.format == 'yaml' else 'json'}"
    path = payload.path or f"sites/{file_name}"
    content = _site_to_yaml(spec) if payload.format == "yaml" else json.dumps(spec, indent=2)
    result = {
        "mode": "repo-ready-export",
        "repository": payload.repository,
        "branch": payload.branch,
        "path": path,
        "site_name": site.name,
        "format": payload.format,
        "files": [{"path": path, "content": content}],
        "next_actions": ["Commit the exported file to the GitOps repository.", "Run import or CI validation against the desired-state contract."],
    }
    store.add_audit(context.username, "gitops.export", f"site:{site.name}", {"path": path, "format": payload.format})
    return result


@app.post("/gitops/import")
def gitops_import(payload: GitOpsImportPayload, context: AuthContext = write_sites) -> dict[str, Any]:
    if payload.site:
        spec = SiteSpec.model_validate(payload.site)
    elif payload.content:
        parsed = _parse_simple_yaml(payload.content) if "site:" in payload.content else json.loads(payload.content)
        spec = SiteSpec.model_validate(parsed)
    else:
        raise HTTPException(status_code=422, detail="site or content is required")
    record = store.upsert_site(spec, tenant_id=_tenant_scope(context))
    store.add_audit(context.username, "gitops.import", f"site:{record.name}", {"source": payload.source})
    return record.model_dump(mode="json")


@app.post("/access/users")
def create_or_update_user(payload: UserPayload, _: Any = manage_access) -> dict[str, Any]:
    if not payload.username.strip():
        raise HTTPException(status_code=422, detail="username is required")
    known_roles = {role.name for role in store.list_roles()}
    unknown_roles = [role for role in payload.roles if role not in known_roles]
    if unknown_roles:
        raise HTTPException(status_code=422, detail=f"unknown roles: {', '.join(unknown_roles)}")
    if payload.password:
        _validate_password_policy(payload.password)
    user = UserRecord(
        username=payload.username.strip(),
        tenant_id=payload.tenant_id.strip() or "default",
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
def list_site_records(context: AuthContext = read_sites) -> dict[str, Any]:
    return {"sites": [site.model_dump(mode="json") for site in store.list_sites(_tenant_scope(context))]}


@app.post("/sites")
def create_or_update_site(payload: SitePayload, context: AuthContext = write_sites) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    result = store.upsert_site(spec, tenant_id=_tenant_scope(context)).model_dump(mode="json")
    store.add_audit("api", "site.upsert", f"site:{spec.site.name}", {"platform": spec.platform.type.value})
    return result


@app.get("/sites/{site_name}")
def get_site_record(site_name: str, context: AuthContext = read_sites) -> dict[str, Any]:
    site = store.get_site(site_name, _tenant_scope(context))
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site.model_dump(mode="json")


@app.get("/sites/{site_name}/topology")
def site_topology(site_name: str, context: AuthContext = read_sites) -> dict[str, Any]:
    site = store.get_site(site_name, _tenant_scope(context))
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    spec = spec_from_record(site)
    nodes = [
        {"id": f"node:{node.serial}", "label": node.serial, "type": "host", "bmc_ip": node.bmc_ip, "role": node.role}
        for node in spec.hardware.nodes
    ]
    networks = [
        {"id": "network:management", "label": f"Mgmt VLAN {spec.network.management_vlan}", "type": "network"},
        {"id": "network:storage", "label": f"Storage VLAN {spec.network.storage_vlan}", "type": "network"},
        {"id": "network:vm", "label": f"VM VLAN {spec.network.vm_vlan}", "type": "network"},
    ]
    return {
        "site_name": site.name,
        "topology": spec.platform.topology,
        "nodes": [
            {"id": "platform", "label": spec.platform.type.value, "type": "platform", "topology": spec.platform.topology},
            *networks,
            *nodes,
        ],
        "links": [
            *[{"source": "platform", "target": network["id"], "type": "uses"} for network in networks],
            *[
                {"source": f"node:{node.serial}", "target": network["id"], "type": "connected"}
                for node in spec.hardware.nodes
                for network in networks
            ],
        ],
    }


@app.delete("/sites/{site_name}")
def delete_site_record(site_name: str, context: AuthContext = delete_sites) -> dict[str, bool]:
    deleted = store.delete_site(site_name, _tenant_scope(context))
    store.add_audit("api", "site.delete", f"site:{site_name}", {"deleted": deleted})
    return {"deleted": deleted}


@app.post("/sites/{site_name}/jobs/{action}")
def run_site_job(site_name: str, action: str, payload: JobPayload | None = None, authorization: str | None = Header(default=None)) -> dict[str, str]:
    if action not in {"validate", "plan", "inventory", "preflight", "artifacts", "mount-iso", "eject-iso", "deploy-azure-local", "drift-detect", "node-replacement"}:
        raise HTTPException(status_code=400, detail="unsupported action")
    context = require_permission(_permission_for_action(action), store)(authorization)
    if store.get_site(site_name, _tenant_scope(context)) is None:
        raise HTTPException(status_code=404, detail="site not found")
    params = payload.model_dump(mode="json", exclude_none=True) if payload else {}
    if _approval_required(action, params):
        approval_id = params.get("approval_id")
        approval = store.get_approval(approval_id) if approval_id else None
        if approval is None or approval.status != "approved" or approval.site_name != site_name or approval.action != action:
            policy = _approval_policy_for_action(action)
            pending = store.create_approval(
                site_name,
                action,
                context.username,
                {
                    "params": _approval_safe_params(params),
                    "reason": _approval_reason(action, policy),
                    "policy": policy.model_dump(mode="json") if policy else None,
                },
                required_approvals=policy.min_approvals if policy else 1,
                approver_roles=policy.approver_roles if policy else [],
                expires_minutes=policy.expires_minutes if policy else 1440,
            )
            store.add_audit(context.username, "approval.requested", f"approval:{pending.id}", {"site": site_name, "action": action, "required_approvals": pending.required_approvals})
            return {"approval_id": pending.id, "status": "approval-required"}
    return {"job_id": jobs.submit(site_name, action, params)}


@app.get("/jobs")
def list_job_records(site_name: str | None = None, context: AuthContext = read_jobs) -> dict[str, Any]:
    return {"jobs": [job.model_dump(mode="json") for job in store.list_jobs(site_name, _tenant_scope(context))]}


@app.get("/jobs/{job_id}")
def get_job_record(job_id: str, context: AuthContext = read_jobs) -> dict[str, Any]:
    job = _job_for_context(job_id, context)
    return job.model_dump(mode="json")


@app.get("/jobs/{job_id}/events")
def get_job_events(job_id: str, context: AuthContext = read_jobs) -> dict[str, Any]:
    _job_for_context(job_id, context)
    return {"events": [event.model_dump(mode="json") for event in store.list_job_events(job_id)]}


@app.get("/jobs/{job_id}/report")
def get_job_report(job_id: str, context: AuthContext = Depends(require_permission("export-reports", store))) -> dict[str, Any]:
    job = _job_for_context(job_id, context)
    site = store.get_site(job.site_name, _tenant_scope(context))
    events = store.list_job_events(job_id)
    return {
        "report_type": "strataone-job-execution",
        "generated_at": datetime.now(UTC).isoformat(),
        "job": job.model_dump(mode="json"),
        "site": site.model_dump(mode="json") if site else None,
        "events": [event.model_dump(mode="json") for event in events],
        "summary": {
            "status": job.status,
            "event_count": len(events),
            "failed": job.status == "failed",
            "duration_known": bool(job.started_at and job.finished_at),
        },
    }


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, context: AuthContext = Depends(require_permission("run-plan", store))) -> dict[str, Any]:
    _job_for_context(job_id, context)
    job = store.cancel_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    store.add_audit(context.username, "job.cancel", f"job:{job_id}", {"status": job.status})
    return job.model_dump(mode="json")


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, context: AuthContext = Depends(require_permission("run-plan", store))) -> dict[str, Any]:
    job = _job_for_context(job_id, context)
    new_job_id = jobs.submit(job.site_name, job.action, job.params)
    store.add_audit(context.username, "job.retry", f"job:{job_id}", {"new_job_id": new_job_id})
    return {"job_id": new_job_id, "status": "queued"}


@app.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, context: AuthContext = Depends(require_permission("run-plan", store))) -> dict[str, Any]:
    job = _job_for_context(job_id, context)
    if job.status not in {"failed", "canceled"}:
        raise HTTPException(status_code=409, detail="only failed or canceled jobs can be resumed")
    params = {**job.params, "resume_from_job_id": job_id}
    new_job_id = jobs.submit(job.site_name, job.action, params)
    store.add_audit(context.username, "job.resume", f"job:{job_id}", {"new_job_id": new_job_id})
    return {"job_id": new_job_id, "status": "queued", "resume_from_job_id": job_id}


@app.get("/jobs/{job_id}/events/stream")
def stream_job_events(job_id: str, context: AuthContext = read_jobs) -> StreamingResponse:
    _job_for_context(job_id, context)
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


@app.websocket("/jobs/{job_id}/events/ws")
async def websocket_job_events(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    try:
        if auth_enabled():
            try:
                context = authenticate(websocket.headers.get("Authorization"), store)
            except HTTPException as exc:
                await websocket.send_json({"type": "error", "status": exc.status_code, "detail": exc.detail})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            if "*" not in context.permissions and "read-jobs" not in context.permissions:
                await websocket.send_json({"type": "error", "status": 403, "detail": "permission required: read-jobs"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            job = store.get_job(job_id)
            if job is None or not _tenant_matches(job.tenant_id, context):
                await websocket.send_json({"type": "error", "status": 404, "detail": "job not found"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        seen: set[str] = set()
        for _ in range(120):
            events = store.list_job_events(job_id)
            for event in events:
                if event.id in seen:
                    continue
                seen.add(event.id)
                await websocket.send_json({"type": "job-event", "event": event.model_dump(mode="json")})
            job = store.get_job(job_id)
            if job and job.status in {"succeeded", "failed", "canceled"} and all(event.id in seen for event in events):
                await websocket.send_json({"type": "job-complete", "job": job.model_dump(mode="json")})
                break
            time.sleep(1)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/audit")
def list_audit_log(limit: int = 100, _: Any = read_audit) -> dict[str, Any]:
    return {"audit": [item.model_dump(mode="json") for item in store.list_audit(limit)]}


@app.get("/approvals")
def list_approval_records(context: AuthContext = read_jobs) -> dict[str, Any]:
    store.expire_pending_approvals()
    approvals = [item for item in store.list_approvals() if _approval_visible(item, context)]
    return {"approvals": [item.model_dump(mode="json") for item in approvals]}


@app.post("/approvals/{approval_id}/approve")
def approve_request(approval_id: str, context: AuthContext = Depends(require_permission("manage-settings", store))) -> dict[str, Any]:
    _assert_can_approve(approval_id, context)
    approval = store.approve(approval_id, context.username, context.roles)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    store.add_audit(context.username, "approval.vote", f"approval:{approval_id}", approval.model_dump(mode="json"))
    return approval.model_dump(mode="json")


@app.post("/approvals/{approval_id}/run")
def approve_and_run(approval_id: str, context: AuthContext = Depends(require_permission("manage-settings", store))) -> dict[str, Any]:
    _assert_can_approve(approval_id, context)
    approval = store.approve(approval_id, context.username, context.roles)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if approval.status != "approved":
        store.add_audit(context.username, "approval.vote.pending", f"approval:{approval_id}", approval.model_dump(mode="json"))
        return {"approval": approval.model_dump(mode="json"), "job_id": None, "status": "pending-approval"}
    params = dict(approval.detail.get("params") or {})
    params["approval_id"] = approval_id
    job_id = jobs.submit(approval.site_name, approval.action, params)
    store.add_audit(context.username, "approval.approved.run", f"approval:{approval_id}", {"job_id": job_id, "action": approval.action, "site": approval.site_name})
    return {"approval": approval.model_dump(mode="json"), "job_id": job_id, "status": "queued"}


@app.post("/approvals/{approval_id}/reject")
def reject_request(approval_id: str, payload: ApprovalDecisionPayload | None = None, context: AuthContext = Depends(require_permission("manage-settings", store))) -> dict[str, Any]:
    _assert_can_approve(approval_id, context)
    approval = store.reject(approval_id, context.username, payload.reason if payload else "")
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    store.add_audit(context.username, "approval.rejected", f"approval:{approval_id}", approval.model_dump(mode="json"))
    return approval.model_dump(mode="json")


@app.post("/sites/{site_name}/artifacts")
def generate_artifacts(site_name: str, context: AuthContext = Depends(require_permission("generate-artifacts", store))) -> dict[str, Any]:
    site = _site_for_context(site_name, context)
    return ArtifactGenerator().generate(spec_from_record(site)).model_dump(mode="json")


@app.get("/sites/{site_name}/artifacts/files")
def list_artifact_files(site_name: str, context: AuthContext = read_sites) -> dict[str, Any]:
    _site_for_context(site_name, context)
    site_dir = _artifact_site_dir(site_name)
    files = []
    if site_dir.exists():
        for path in sorted(site_dir.iterdir()):
            if path.is_file():
                stat = path.stat()
                files.append(ArtifactFileRecord(name=path.name, path=str(path), size_bytes=stat.st_size, updated_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()).model_dump(mode="json"))
    return {"site_name": site_name, "output_dir": str(site_dir), "files": files}


@app.get("/sites/{site_name}/artifacts/files/{file_name}")
def get_artifact_file(site_name: str, file_name: str, context: AuthContext = read_sites) -> dict[str, Any]:
    _site_for_context(site_name, context)
    if "/" in file_name or "\\" in file_name or file_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="invalid file name")
    path = _artifact_site_dir(site_name) / file_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file not found")
    return {"site_name": site_name, "name": file_name, "content": path.read_text(encoding="utf-8")}


@app.get("/sites/{site_name}/artifacts/bundle.zip")
def download_artifact_bundle(site_name: str, context: AuthContext = read_sites) -> StreamingResponse:
    _site_for_context(site_name, context)
    site_dir = _artifact_site_dir(site_name)
    if not site_dir.exists():
        raise HTTPException(status_code=404, detail="artifact bundle not generated")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(site_dir.iterdir()):
            if path.is_file():
                archive.write(path, arcname=path.name)
    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{site_name}-strataone-artifacts.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


@app.get("/sites/{site_name}/inventory")
def get_site_inventory(site_name: str, context: AuthContext = read_inventory) -> dict[str, Any]:
    inventory = store.get_inventory(site_name, _tenant_scope(context))
    if inventory is None:
        raise HTTPException(status_code=404, detail="inventory not found")
    return inventory.model_dump(mode="json")


@app.post("/sites/{site_name}/inventory")
def save_site_inventory(site_name: str, payload: InventoryPayload, context: AuthContext = write_inventory) -> dict[str, Any]:
    if store.get_site(site_name, _tenant_scope(context)) is None:
        raise HTTPException(status_code=404, detail="site not found")
    report = InventoryReport.model_validate(payload.inventory)
    if report.site_name != site_name:
        raise HTTPException(status_code=422, detail="inventory site_name does not match route")
    return store.save_inventory(report).model_dump(mode="json")


@app.post("/sites/validate")
def validate_site(payload: SitePayload, _: Any = Depends(require_permission("run-validate", store))) -> dict[str, Any]:
    spec = _spec_from_payload(payload)
    issues = _site_operational_issues(spec)
    return {
        "valid": len([issue for issue in issues if issue["severity"] == "error"]) == 0,
        "site_name": spec.site.name,
        "platform": spec.platform.type.value,
        "hardware_provider": spec.hardware.vendor,
        "nodes": len(spec.hardware.nodes),
        "issues": issues,
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


def _site_for_context(site_name: str, context: AuthContext):
    site = store.get_site(site_name, _tenant_scope(context))
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site


def _job_for_context(job_id: str, context: AuthContext):
    job = store.get_job(job_id)
    if job is None or not _tenant_matches(job.tenant_id, context):
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _tenant_matches(tenant_id: str, context: AuthContext) -> bool:
    scope = _tenant_scope(context)
    return scope == "*" or tenant_id == scope


def _approval_visible(approval, context: AuthContext) -> bool:
    site = store.get_site(approval.site_name, _tenant_scope(context))
    return site is not None


def _permission_for_action(action: str) -> str:
    return {
        "validate": "run-validate",
        "plan": "run-plan",
        "inventory": "run-inventory",
        "preflight": "run-preflight",
        "artifacts": "generate-artifacts",
        "mount-iso": "mount-iso",
        "eject-iso": "mount-iso",
        "deploy-azure-local": "run-plan",
        "drift-detect": "run-preflight",
        "node-replacement": "run-preflight",
    }[action]


def _tenant_scope(context: AuthContext) -> str:
    if not os.getenv("STRATAONE_TENANT_ENFORCEMENT", "true").lower() in {"1", "true", "yes", "on"}:
        return "*"
    return context.tenant_id or "default"


def _provider_harness_result(provider: ProviderInfo, payload: ProviderHarnessPayload) -> dict[str, Any]:
    mode = "live" if payload.live else "contract"
    checks = [
        {"name": "provider_registered", "status": "passed"},
        {"name": "operation_declared", "status": "passed" if payload.operation else "failed"},
        {"name": "target_declared", "status": "passed" if payload.target or not payload.live else "failed"},
    ]
    if provider.type == "hardware":
        checks.append({"name": "redfish_contract", "status": "passed"})
    else:
        checks.append({"name": "platform_contract", "status": "passed"})
    status_value = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {
        "provider": provider.name,
        "provider_type": provider.type,
        "operation": payload.operation,
        "mode": mode,
        "target": payload.target,
        "status": status_value,
        "checks": checks,
        "summary": f"{provider.name} {payload.operation} validation completed in {mode} mode.",
        "live_execution": payload.live,
        "credential_ref": payload.credential_ref,
    }


def _approval_required(action: str, params: dict[str, Any]) -> bool:
    if not os.getenv("STRATAONE_REQUIRE_APPROVALS", "true").lower() in {"1", "true", "yes", "on"}:
        return False
    policy = _approval_policy_for_action(action)
    if policy is not None:
        return policy.enabled
    return action in _approval_required_actions()


def _approval_policy_for_action(action: str):
    return store.get_approval_policy(action)


def _approval_reason(action: str, policy) -> str:
    if policy:
        roles = ", ".join(policy.approver_roles) if policy.approver_roles else "any approver"
        return f"{action} requires {policy.min_approvals} approval(s) from {roles} before execution."
    return f"{action} is configured as a protected live-impact action."


def _approval_required_actions() -> set[str]:
    configured = os.getenv("STRATAONE_APPROVAL_ACTIONS", "mount-iso,deploy-azure-local,node-replacement")
    return {action.strip() for action in configured.split(",") if action.strip()}


def _approval_safe_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: ("***" if key in {"password", "username"} else value) for key, value in params.items()}


def _assert_can_approve(approval_id: str, context: AuthContext) -> None:
    approval = store.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if not _approval_visible(approval, context):
        raise HTTPException(status_code=404, detail="approval not found")
    if approval.status != "pending":
        if approval.status == "expired":
            raise HTTPException(status_code=409, detail="approval request has expired")
        return
    if approval.expires_at and approval.expires_at <= datetime.now(UTC).isoformat():
        store.expire_approval(approval_id)
        raise HTTPException(status_code=409, detail="approval request has expired")
    if approval.approver_roles and not set(context.roles).intersection(approval.approver_roles):
        raise HTTPException(status_code=403, detail=f"approval requires one of: {', '.join(approval.approver_roles)}")


def _validate_password_policy(password: str) -> None:
    min_length = int(os.getenv("STRATAONE_PASSWORD_MIN_LENGTH", "12"))
    checks = {
        "uppercase": any(char.isupper() for char in password),
        "lowercase": any(char.islower() for char in password),
        "number": any(char.isdigit() for char in password),
        "symbol": any(not char.isalnum() for char in password),
    }
    if len(password) < min_length or sum(1 for passed in checks.values() if passed) < 3:
        raise HTTPException(status_code=422, detail=f"password must be at least {min_length} characters and include at least three of: uppercase, lowercase, number, symbol")


def _site_operational_issues(spec: SiteSpec) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not spec.hardware.nodes:
        issues.append({"severity": "error", "field": "hardware.nodes", "message": "At least one node is required."})
    serials: set[str] = set()
    for node in spec.hardware.nodes:
        if node.serial in serials:
            issues.append({"severity": "error", "field": "hardware.nodes.serial", "message": f"Duplicate node serial {node.serial}."})
        serials.add(node.serial)
    if spec.platform.type.value == "azure-local" and spec.platform.azure is None:
        issues.append({"severity": "error", "field": "platform.azure", "message": "Azure Local deployments require Azure subscription, tenant, resource group, and region."})
    if spec.network.management_vlan == spec.network.storage_vlan or spec.network.management_vlan == spec.network.vm_vlan:
        issues.append({"severity": "warning", "field": "network.vlan", "message": "Management VLAN should be isolated from storage and VM traffic."})
    return issues


def _redact_secret(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload)
    if safe.get("reference"):
        safe["reference"] = "***"
    if isinstance(safe.get("metadata"), dict):
        safe["metadata"] = {key: ("***" if "password" in key.lower() or "token" in key.lower() else value) for key, value in safe["metadata"].items()}
    return safe


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("password", "secret", "token", "key", "credential")):
                redacted[key] = "***"
            else:
                redacted[key] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _safe_outbound_request(method: str, url: str, *, timeout: float, max_redirects: int = 3, **kwargs: Any) -> requests.Response:
    current_url = str(url)
    for _ in range(max_redirects + 1):
        _assert_safe_outbound_url(current_url)
        response = requests.request(method, current_url, timeout=timeout, allow_redirects=False, **kwargs)
        if response.is_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise HTTPException(status_code=422, detail="outbound redirect did not include a location")
            current_url = urljoin(current_url, location)
            continue
        return response
    raise HTTPException(status_code=422, detail="outbound URL exceeded redirect limit")


def _assert_safe_outbound_url(url: str) -> None:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="outbound URL must be http or https with a hostname")
    host = parsed.hostname.strip().lower()
    blocked_hosts = {"localhost", "localhost.localdomain"}
    if host in blocked_hosts or host.endswith(".localhost"):
        raise HTTPException(status_code=422, detail="outbound URL host is not allowed")
    try:
        addresses = [ip_address(host)]
    except ValueError:
        try:
            addresses = [ip_address(result[4][0]) for result in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)]
        except socket.gaierror as exc:
            raise HTTPException(status_code=422, detail="outbound URL host could not be resolved") from exc
    if any(_is_blocked_outbound_ip(address) for address in addresses):
        raise HTTPException(status_code=422, detail="outbound URL resolves to a private or reserved address")


def _is_blocked_outbound_ip(address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _provider_config_template(provider_name: str, provider_type: str) -> dict[str, Any]:
    if provider_type == "hardware":
        return {
            "endpoint": "https://bmc.example.com",
            "credential_ref": "branch-bmc",
            "tls_verify": False,
            "capabilities": ["inventory", "virtual-media", "power"],
            "lab_validated": False,
        }
    if provider_name == "azure-local":
        return {
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-strataone",
            "region": "westeurope",
            "credential_ref": "azure-local-spn",
            "approval_required": True,
        }
    return {
        "endpoint": "https://provider.example.com",
        "credential_ref": f"{provider_name}-credentials",
        "approval_required": True,
        "lab_validated": False,
    }


def _candidate_serial(candidate: dict[str, Any], index: int) -> str:
    value = candidate.get("serial") or candidate.get("uuid") or candidate.get("bmc_ip") or f"node-{index}"
    serial = "".join(char if char.isalnum() or char in "_.:-" else "-" for char in str(value))
    return serial[:64] or f"node-{index}"


def _deployment_templates() -> list[dict[str, Any]]:
    base = load_site_spec(Path("examples/azure-local-branch.yaml")).model_dump(mode="json")
    templates = [
        (
            "azure-local-branch",
            "Azure Local Branch",
            "Two-node Azure Local branch or edge deployment with Arc workloads.",
            "branch",
            ["Azure Local", "Arc", "two-node"],
            base,
        ),
        (
            "azure-local-edge-scale",
            "Azure Local Edge Scale",
            "Four-node Azure Local edge cluster for HA workloads and AKS hybrid.",
            "edge",
            ["Azure Local", "AKS", "four-node"],
            _template_variant(
                base,
                "azure-local",
                "al-edge-scale",
                "al-edge-scale-001",
                "edge-hci",
                nodes=4,
                topology="four-node-switched",
                hardware_vendor="dell-idrac",
                network={"management_vlan": 210, "storage_vlan": 220, "vm_vlan": 230},
                azure={"resource_group": "rg-al-edge-scale", "region": "westeurope"},
                workloads={"aks": True, "arc_vms": True, "avd": False, "kubernetes": False},
                settings={"deployment_mode": "cloud-witness", "storage_spaces_direct": True},
            ),
        ),
        (
            "azure-local-stretched",
            "Azure Local Stretched",
            "Four-node stretched Azure Local design for two-room or metro resilient sites.",
            "resilience",
            ["Azure Local", "stretched", "witness"],
            _template_variant(
                base,
                "azure-local",
                "al-stretched-001",
                "al-stretched-001",
                "stretched-hci",
                nodes=4,
                topology="stretched-two-site",
                hardware_vendor="hpe-ilo",
                network={"management_vlan": 310, "storage_vlan": 320, "vm_vlan": 330},
                azure={"resource_group": "rg-al-stretched", "region": "northeurope"},
                workloads={"aks": False, "arc_vms": True, "avd": False, "kubernetes": False},
                settings={"fault_domains": ["room-a", "room-b"], "witness": "cloud"},
            ),
        ),
        (
            "vsphere-management",
            "vSphere Management Cluster",
            "Three-host vSphere management cluster for vCenter, tooling, and core services.",
            "management",
            ["vSphere", "vCenter", "management"],
            _template_variant(
                base,
                "vmware-vsphere",
                "vsphere-mgmt-001",
                "vcsa-mgmt-001",
                "management-cluster",
                nodes=3,
                topology="three-node-vsan",
                hardware_vendor="dell-idrac",
                network={"management_vlan": 410, "storage_vlan": 420, "vm_vlan": 430},
                workloads={"aks": False, "arc_vms": False, "avd": False, "kubernetes": False},
                settings={"vcenter": "vcenter.example.com", "datacenter": "dc01", "vsan": True},
            ),
        ),
        (
            "vsphere-workload",
            "vSphere Workload Cluster",
            "Four-host vSphere workload cluster with shared management and VM networks.",
            "private-cloud",
            ["vSphere", "ESXi", "workload"],
            _template_variant(
                base,
                "vmware-vsphere",
                "vsphere-workload-001",
                "compute-cluster-001",
                "private-cloud",
                nodes=4,
                topology="four-node-vsan",
                hardware_vendor="lenovo-xclarity",
                network={"management_vlan": 440, "storage_vlan": 450, "vm_vlan": 460},
                settings={"vcenter": "vcenter.example.com", "datacenter": "dc01", "drs": True, "ha": True},
            ),
        ),
        (
            "nutanix-ahv-edge",
            "Nutanix AHV Edge",
            "Three-node Nutanix AHV edge cluster aligned to Prism-managed operations.",
            "edge-hci",
            ["AHV", "Prism", "edge"],
            _template_variant(
                base,
                "nutanix-ahv",
                "ahv-edge-001",
                "ahv-edge-001",
                "edge-hci",
                nodes=3,
                topology="three-node-ahv",
                hardware_vendor="generic-redfish",
                network={"management_vlan": 510, "storage_vlan": 520, "vm_vlan": 530},
                settings={"prism_element": "https://prism-element.example.com:9440", "replication": "async"},
            ),
        ),
        (
            "nutanix-ahv-robo",
            "Nutanix AHV ROBO",
            "Two-node AHV remote-office template with witness-assisted resilience.",
            "branch",
            ["AHV", "ROBO", "witness"],
            _template_variant(
                base,
                "nutanix-ahv",
                "ahv-robo-001",
                "ahv-robo-001",
                "branch-hci",
                nodes=2,
                topology="two-node-witness",
                hardware_vendor="supermicro-redfish",
                network={"management_vlan": 540, "storage_vlan": 550, "vm_vlan": 560},
                settings={"witness": "prism-central", "replication": "none"},
            ),
        ),
        (
            "proxmox-lab",
            "Proxmox Lab",
            "Compact Proxmox VE lab cluster using Redfish hardware discovery.",
            "lab",
            ["Proxmox", "lab", "Ceph optional"],
            _template_variant(
                base,
                "proxmox",
                "proxmox-lab-001",
                "px-lab-001",
                "lab",
                nodes=2,
                topology="two-node-lab",
                hardware_vendor="generic-redfish",
                network={"management_vlan": 610, "storage_vlan": 620, "vm_vlan": 630},
                settings={"ceph": False, "ha": False, "repository": "enterprise-disabled"},
            ),
        ),
        (
            "proxmox-edge",
            "Proxmox Edge",
            "Three-node Proxmox VE edge cluster with Ceph-backed workload storage.",
            "edge",
            ["Proxmox", "Ceph", "edge"],
            _template_variant(
                base,
                "proxmox",
                "proxmox-edge-001",
                "px-edge-001",
                "edge-cluster",
                nodes=3,
                topology="three-node-ceph",
                hardware_vendor="supermicro-redfish",
                network={"management_vlan": 640, "storage_vlan": 650, "vm_vlan": 660},
                settings={"ceph": True, "ha": True, "repository": "enterprise"},
            ),
        ),
        (
            "hyper-v-cluster",
            "Hyper-V Cluster",
            "Two-node Windows Hyper-V failover cluster for private-cloud estates.",
            "private-cloud",
            ["Hyper-V", "Windows", "failover"],
            _template_variant(
                base,
                "hyper-v",
                "hyperv-cluster-001",
                "hv-cluster-001",
                "private-cloud",
                nodes=2,
                topology="two-node-failover",
                hardware_vendor="dell-idrac",
                network={"management_vlan": 710, "storage_vlan": 720, "vm_vlan": 730},
                settings={"cluster_witness": "file-share", "s2d": True},
            ),
        ),
        (
            "hyper-v-workload",
            "Hyper-V Workload Scale",
            "Four-node Hyper-V cluster for larger Windows Server virtualization estates.",
            "private-cloud",
            ["Hyper-V", "S2D", "scale"],
            _template_variant(
                base,
                "hyper-v",
                "hyperv-workload-001",
                "hv-workload-001",
                "private-cloud",
                nodes=4,
                topology="four-node-s2d",
                hardware_vendor="hpe-ilo",
                network={"management_vlan": 740, "storage_vlan": 750, "vm_vlan": 760},
                settings={"cluster_witness": "cloud", "s2d": True, "live_migration": True},
            ),
        ),
        (
            "kvm-libvirt",
            "KVM Libvirt Cluster",
            "Vendor-neutral KVM/libvirt template for Linux virtualization hosts.",
            "private-cloud",
            ["KVM", "libvirt", "Linux"],
            _template_variant(
                base,
                "kvm",
                "kvm-libvirt-001",
                "kvm-cluster-001",
                "private-cloud",
                nodes=3,
                topology="three-node-linux",
                hardware_vendor="generic-redfish",
                network={"management_vlan": 810, "storage_vlan": 820, "vm_vlan": 830},
                settings={"libvirt": True, "storage_backend": "shared-nfs", "bridge": "br0"},
            ),
        ),
        (
            "kvm-openstack",
            "KVM OpenStack Compute",
            "KVM compute foundation for OpenStack or adjacent cloud stacks.",
            "cloud-compute",
            ["KVM", "OpenStack", "compute"],
            _template_variant(
                base,
                "kvm",
                "kvm-openstack-001",
                "kvm-compute-001",
                "cloud-compute",
                nodes=4,
                topology="four-node-compute",
                hardware_vendor="cisco-intersight",
                network={"management_vlan": 840, "storage_vlan": 850, "vm_vlan": 860},
                settings={"cloud_stack": "openstack", "neutron_bridge": "br-provider", "storage_backend": "ceph"},
            ),
        ),
        (
            "openshift-virtualization",
            "OpenShift Virtualization",
            "Kubernetes-native virtualization target for OpenShift estates.",
            "private-cloud",
            ["OpenShift", "KubeVirt", "virtualization"],
            _template_variant(
                base,
                "openshift-virtualization",
                "ocp-virt-001",
                "ocp-virt-001",
                "private-cloud",
                nodes=3,
                topology="three-node-compact",
                hardware_vendor="lenovo-xclarity",
                network={"management_vlan": 910, "storage_vlan": 920, "vm_vlan": 930},
                workloads={"aks": False, "arc_vms": False, "avd": False, "kubernetes": True},
                settings={"operator": "cnv", "storage_class": "ocs-storagecluster-ceph-rbd"},
            ),
        ),
        (
            "openshift-virtualization-edge",
            "OpenShift Virtualization Edge",
            "Compact OpenShift Virtualization edge profile for remote application platforms.",
            "edge",
            ["OpenShift", "edge", "KubeVirt"],
            _template_variant(
                base,
                "openshift-virtualization",
                "ocp-edge-001",
                "ocp-edge-001",
                "edge-platform",
                nodes=3,
                topology="compact-edge",
                hardware_vendor="dell-idrac",
                network={"management_vlan": 940, "storage_vlan": 950, "vm_vlan": 960},
                workloads={"aks": False, "arc_vms": False, "avd": False, "kubernetes": True},
                settings={"operator": "cnv", "gitops": True, "disconnected": False},
            ),
        ),
    ]
    return [
        {
            "id": template_id,
            "name": name,
            "description": description,
            "category": category,
            "tags": tags,
            "use_case": spec["site"]["deployment_model"],
            "hardware_provider": spec["hardware"]["vendor"],
            "platform": spec["platform"]["type"],
            "nodes": len(spec["hardware"]["nodes"]),
            "spec": spec,
        }
        for template_id, name, description, category, tags, spec in templates
    ]


def _template_variant(
    base: dict[str, Any],
    platform: str,
    site_name: str,
    cluster_name: str,
    deployment_model: str,
    *,
    nodes: int = 2,
    topology: str | None = None,
    hardware_vendor: str = "generic-redfish",
    network: dict[str, Any] | None = None,
    azure: dict[str, Any] | None = None,
    workloads: dict[str, bool] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = json.loads(json.dumps(base))
    spec["site"]["name"] = site_name
    spec["site"]["location"] = f"{site_name}-site"
    spec["site"]["deployment_model"] = deployment_model
    spec["hardware"]["vendor"] = hardware_vendor
    spec["hardware"]["nodes"] = [
        {
            "serial": f"{site_name.upper().replace('-', '')[:12]}{index:02d}",
            "bmc_ip": f"10.{10 + index}.{nodes}.{10 + index}",
            "role": "host",
        }
        for index in range(1, nodes + 1)
    ]
    if network:
        spec["network"].update(network)
    spec["platform"]["type"] = platform
    spec["platform"]["cluster_name"] = cluster_name
    spec["platform"]["topology"] = topology or ("two-node-lab" if platform == "proxmox" else "two-node-cluster")
    if platform == "azure-local":
        spec["platform"].setdefault("azure", {})
        spec["platform"]["azure"].update(azure or {})
    else:
        spec["platform"].pop("azure", None)
    spec["platform"]["settings"] = settings or {}
    spec["workloads"].update(
        workloads
        if workloads is not None
        else {
            "aks": platform == "azure-local",
            "avd": False,
            "arc_vms": platform == "azure-local",
            "kubernetes": platform == "openshift-virtualization",
        }
    )
    return spec


def _compatibility_record(provider: ProviderInfo) -> dict[str, Any]:
    validation = store.list_provider_validation(provider.name)
    badges = []
    if not provider.editable:
        badges.append("StrataOne built-in")
    if provider.vendor_supported:
        badges.append("Vendor supported")
    if any(item.status == "validated" for item in validation):
        badges.append("Lab validated")
    badges.append("Approval gated" if provider.type == "platform" or "redfish" in provider.name or provider.name in {"dell-idrac", "hpe-ilo", "lenovo-xclarity"} else "Read-only capable")
    return {
        "name": provider.name,
        "type": provider.type,
        "source": provider.source,
        "description": provider.description,
        "vendor_supported": provider.vendor_supported,
        "built_in": not provider.editable,
        "lab_validated_operations": [item.operation for item in validation if item.status == "validated"],
        "certification_badges": badges,
        "capabilities": {
            "inventory": provider.type == "hardware",
            "power": provider.type == "hardware",
            "virtual_media": provider.type == "hardware",
            "firmware": provider.type == "hardware",
            "deploy": provider.type == "platform",
            "drift": provider.type == "platform",
            "node_replacement": provider.type == "platform" and provider.name in {"azure-local", "vmware-vsphere", "nutanix-ahv"},
        },
    }


def _release_notes() -> list[dict[str, Any]]:
    changelog = Path("CHANGELOG.md")
    if not changelog.exists():
        return []
    releases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    section = "Notes"
    for raw in changelog.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## ["):
            if current:
                releases.append(current)
            title = line.removeprefix("## [").split("]", 1)[0]
            date = line.split(" - ", 1)[1] if " - " in line else None
            current = {"version": title, "date": date, "sections": {}}
            section = "Notes"
        elif current and line.startswith("### "):
            section = line.removeprefix("### ").strip()
            current["sections"].setdefault(section, [])
        elif current and line.startswith("- "):
            current["sections"].setdefault(section, []).append(line[2:])
    if current:
        releases.append(current)
    return releases


def _site_to_yaml(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                first_key, first_value = next(iter(item.items()))
                if isinstance(first_value, (dict, list)):
                    lines.append(f"{pad}- {first_key}:")
                    lines.append(_site_to_yaml(first_value, indent + 4))
                else:
                    lines.append(f"{pad}- {first_key}: {first_value}")
                for key, nested in list(item.items())[1:]:
                    if isinstance(nested, (dict, list)):
                        lines.append(f"{pad}  {key}:")
                        lines.append(_site_to_yaml(nested, indent + 4))
                    else:
                        lines.append(f"{pad}  {key}: {nested}")
            else:
                lines.append(f"{pad}- {item}")
        return "\n".join(lines)
    if isinstance(value, dict):
        if not value:
            return f"{pad}{{}}"
        lines = []
        for key, item in value.items():
            if item is None:
                lines.append(f"{pad}{key}: null")
                continue
            if isinstance(item, dict) and not item:
                lines.append(f"{pad}{key}: {{}}")
                continue
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_site_to_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {item}")
        return "\n".join(lines)
    return f"{pad}{value}"


def _parse_simple_yaml(content: str) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(content) or {}


def _redact_notification_target(target: str) -> str:
    if "@" in target and not target.startswith("http"):
        name, _, domain = target.partition("@")
        return f"{name[:2]}***@{domain}"
    if target.startswith("http"):
        return target.split("?", 1)[0]
    return "***"


def _artifact_site_dir(site_name: str) -> Path:
    root = Path(os.getenv("STRATAONE_ARTIFACT_DIR", ".strataone/artifacts")).resolve()
    site_dir = (root / site_name).resolve()
    if root != site_dir and root not in site_dir.parents:
        raise HTTPException(status_code=400, detail="artifact path escapes artifact root")
    return site_dir
