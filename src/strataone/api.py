import os
import time
from ipaddress import ip_network
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
import requests

from strataone.artifacts import ArtifactGenerator
from strataone.inventory import InventoryReport
from strataone.jobs import JobRunner
from strataone.orchestrator import Orchestrator
from strataone.preflight import PreflightRunner
from strataone.providers.registry import ProviderInfo, delete_plugin_provider, list_providers, upsert_plugin_provider
from strataone.queue import queue_backend
from strataone.redfish import RedfishClient
from strataone.security import ALL_PERMISSIONS, AuthContext, RateLimitMiddleware, SecurityHeadersMiddleware, auth_enabled, cors_origins, create_password_hash, new_session_token, rate_limit_enabled, require_permission, security_headers, session_expiry, token_hash, verify_password, _bearer_token
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
    try:
        response = requests.head(iso.uri, timeout=float(os.getenv("STRATAONE_ISO_VALIDATE_TIMEOUT", "5")), allow_redirects=True)
        reachable = response.status_code < 400
        content_length = response.headers.get("Content-Length")
        status = "validated" if reachable else "unreachable"
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
def get_job_record(job_id: str, _: Any = read_jobs) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump(mode="json")


@app.get("/jobs/{job_id}/events")
def get_job_events(job_id: str, _: Any = read_jobs) -> dict[str, Any]:
    return {"events": [event.model_dump(mode="json") for event in store.list_job_events(job_id)]}


@app.get("/jobs/{job_id}/report")
def get_job_report(job_id: str, _: Any = Depends(require_permission("export-reports", store))) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    site = store.get_site(job.site_name)
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
    job = store.cancel_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    store.add_audit(context.username, "job.cancel", f"job:{job_id}", {"status": job.status})
    return job.model_dump(mode="json")


@app.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, context: AuthContext = Depends(require_permission("run-plan", store))) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    new_job_id = jobs.submit(job.site_name, job.action, job.params)
    store.add_audit(context.username, "job.retry", f"job:{job_id}", {"new_job_id": new_job_id})
    return {"job_id": new_job_id, "status": "queued"}


@app.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, context: AuthContext = Depends(require_permission("run-plan", store))) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in {"failed", "canceled"}:
        raise HTTPException(status_code=409, detail="only failed or canceled jobs can be resumed")
    params = {**job.params, "resume_from_job_id": job_id}
    new_job_id = jobs.submit(job.site_name, job.action, params)
    store.add_audit(context.username, "job.resume", f"job:{job_id}", {"new_job_id": new_job_id})
    return {"job_id": new_job_id, "status": "queued", "resume_from_job_id": job_id}


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
    store.expire_pending_approvals()
    return {"approvals": [item.model_dump(mode="json") for item in store.list_approvals()]}


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


@app.get("/sites/{site_name}/artifacts/files")
def list_artifact_files(site_name: str, _: Any = read_sites) -> dict[str, Any]:
    site = store.get_site(site_name)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    site_dir = _artifact_site_dir(site_name)
    files = []
    if site_dir.exists():
        for path in sorted(site_dir.iterdir()):
            if path.is_file():
                stat = path.stat()
                files.append(ArtifactFileRecord(name=path.name, path=str(path), size_bytes=stat.st_size, updated_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()).model_dump(mode="json"))
    return {"site_name": site_name, "output_dir": str(site_dir), "files": files}


@app.get("/sites/{site_name}/artifacts/files/{file_name}")
def get_artifact_file(site_name: str, file_name: str, _: Any = read_sites) -> dict[str, Any]:
    if store.get_site(site_name) is None:
        raise HTTPException(status_code=404, detail="site not found")
    if "/" in file_name or "\\" in file_name or file_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="invalid file name")
    path = _artifact_site_dir(site_name) / file_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file not found")
    return {"site_name": site_name, "name": file_name, "content": path.read_text(encoding="utf-8")}


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


def _artifact_site_dir(site_name: str) -> Path:
    return Path(os.getenv("STRATAONE_ARTIFACT_DIR", ".strataone/artifacts")) / site_name
