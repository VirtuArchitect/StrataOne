import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from strataone.inventory import InventoryReport
from strataone.state import SiteSpec


class SiteRecord(BaseModel):
    name: str
    tenant_id: str = "default"
    spec: dict[str, Any]
    platform: str
    hardware_provider: str
    nodes: int
    created_at: str
    updated_at: str


class JobRecord(BaseModel):
    id: str
    tenant_id: str = "default"
    site_name: str
    action: str
    status: str
    params: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class InventoryRecord(BaseModel):
    site_name: str
    tenant_id: str = "default"
    report: dict[str, Any]
    reachable_nodes: int
    total_nodes: int
    collected_at: str


class RoleRecord(BaseModel):
    name: str
    description: str
    permissions: list[str]
    built_in: bool = False
    created_at: str
    updated_at: str


class UserRecord(BaseModel):
    username: str
    tenant_id: str = "default"
    display_name: str
    email: str
    roles: list[str]
    status: str = "active"
    password_configured: bool = False
    created_at: str
    updated_at: str


class AuditRecord(BaseModel):
    id: str
    actor: str
    action: str
    resource: str
    detail: dict[str, Any]
    created_at: str


class ApprovalRecord(BaseModel):
    id: str
    site_name: str
    action: str
    status: str
    requested_by: str
    approved_by: str | None = None
    detail: dict[str, Any] = {}
    votes: list[dict[str, Any]] = []
    required_approvals: int = 1
    approver_roles: list[str] = []
    expires_at: str | None = None
    created_at: str
    updated_at: str


class ApprovalPolicyRecord(BaseModel):
    id: str
    action: str
    enabled: bool = True
    approver_roles: list[str] = []
    min_approvals: int = 1
    expires_minutes: int = 1440
    created_at: str
    updated_at: str


class JobEventRecord(BaseModel):
    id: str
    job_id: str
    level: str
    message: str
    detail: dict[str, Any]
    created_at: str


class ProviderConfigRecord(BaseModel):
    provider_name: str
    config: dict[str, Any]
    updated_at: str


class ProviderValidationRecord(BaseModel):
    id: str
    provider_name: str
    operation: str
    status: str
    lab: str | None = None
    evidence: str | None = None
    notes: str | None = None
    created_at: str


class ProviderValidationRunRecord(BaseModel):
    id: str
    provider_name: str
    operation: str
    mode: str
    status: str
    target: str | None = None
    result: dict[str, Any] = {}
    created_at: str


class SecretRefRecord(BaseModel):
    name: str
    type: str
    provider: str
    reference: str
    metadata: dict[str, Any] = {}
    created_at: str
    updated_at: str


class DiscoveryRunRecord(BaseModel):
    id: str
    name: str
    cidr: str
    provider: str
    status: str
    result: dict[str, Any]
    created_at: str
    updated_at: str


class IsoRecord(BaseModel):
    name: str
    uri: str
    checksum: str | None = None
    checksum_algorithm: str = "sha256"
    status: str = "registered"
    created_at: str
    updated_at: str


class SessionRecord(BaseModel):
    token_hash: str
    username: str
    created_at: str
    expires_at: str


class MigrationRecord(BaseModel):
    version: str
    applied_at: str


class DbConnection(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        ...

    def __enter__(self) -> "DbConnection":
        ...

    def __exit__(self, exc_type, exc, tb) -> None:
        ...


class PostgresConnection:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL backend requires the psycopg[binary] package") from exc
        self._conn = psycopg.connect(dsn, row_factory=dict_row)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self._conn.execute(_postgres_sql(sql), params)

    def __enter__(self) -> "PostgresConnection":
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._conn.__exit__(exc_type, exc, tb)


class StrataStore:
    def __init__(self, path: Path | None = None) -> None:
        self.backend = os.getenv("STRATAONE_STATE_BACKEND", "sqlite").lower()
        self.postgres_dsn = os.getenv("STRATAONE_POSTGRES_DSN", "postgresql://strataone:strataone@postgres:5432/strataone")
        self.path = path or Path(os.getenv("STRATAONE_DB", ".strataone/strataone.db"))
        if self.backend == "sqlite":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> DbConnection:
        if self.backend == "postgres":
            return PostgresConnection(self.postgres_dsn)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sites (
                    name TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    spec_json TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    hardware_provider TEXT NOT NULL,
                    nodes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    site_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    params_json TEXT,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    site_name TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    report_json TEXT NOT NULL,
                    reachable_nodes INTEGER NOT NULL,
                    total_nodes INTEGER NOT NULL,
                    collected_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    built_in INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    display_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    password_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    site_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    approved_by TEXT,
                    detail_json TEXT NOT NULL,
                    votes_json TEXT NOT NULL DEFAULT '[]',
                    required_approvals INTEGER NOT NULL DEFAULT 1,
                    approver_roles_json TEXT NOT NULL DEFAULT '[]',
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_policies (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    approver_roles_json TEXT NOT NULL,
                    min_approvals INTEGER NOT NULL,
                    expires_minutes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_events (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_configs (
                    provider_name TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_validation (
                    id TEXT PRIMARY KEY,
                    provider_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    lab TEXT,
                    evidence TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_validation_runs (
                    id TEXT PRIMARY KEY,
                    provider_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secret_refs (
                    name TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    cidr TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS iso_registry (
                    name TEXT PRIMARY KEY,
                    uri TEXT NOT NULL,
                    checksum TEXT,
                    checksum_algorithm TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            if self.backend == "sqlite":
                self._ensure_column(conn, "jobs", "params_json", "TEXT")
                self._ensure_column(conn, "sites", "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
                self._ensure_column(conn, "jobs", "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
                self._ensure_column(conn, "inventory", "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
                self._ensure_column(conn, "users", "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
                self._ensure_column(conn, "users", "password_hash", "TEXT")
                self._ensure_column(conn, "approvals", "votes_json", "TEXT NOT NULL DEFAULT '[]'")
                self._ensure_column(conn, "approvals", "required_approvals", "INTEGER NOT NULL DEFAULT 1")
                self._ensure_column(conn, "approvals", "approver_roles_json", "TEXT NOT NULL DEFAULT '[]'")
                self._ensure_column(conn, "approvals", "expires_at", "TEXT")
            if self.backend == "postgres":
                conn.execute("ALTER TABLE sites ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'")
                conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'")
                conn.execute("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'")
                conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'")
                conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
                conn.execute("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS votes_json TEXT NOT NULL DEFAULT '[]'")
                conn.execute("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS required_approvals INTEGER NOT NULL DEFAULT 1")
                conn.execute("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS approver_roles_json TEXT NOT NULL DEFAULT '[]'")
                conn.execute("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS expires_at TEXT")
        self.apply_migrations()
        self.seed_access_defaults()

    def apply_migrations(self) -> None:
        migrations = [
            ("001_core_state", "Core site, job, inventory, access, and session tables"),
            ("002_audit_approval_events", "Audit log, approval gates, job events, and provider configs"),
            ("003_secrets_discovery", "Secret references and discovery run history"),
            ("004_iso_job_controls", "ISO registry and operator job control primitives"),
            ("005_approval_policy", "Configurable approval policy rules"),
            ("006_approval_votes_provider_validation", "Approval votes and provider validation evidence"),
            ("007_tenant_provider_validation_runs", "Tenant metadata and live provider validation run history"),
        ]
        applied = {item.version for item in self.list_migrations()}
        with self._connect() as conn:
            for version, _description in migrations:
                if version in applied:
                    continue
                conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, _now()))

    def list_migrations(self) -> list[MigrationRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
        return [MigrationRecord(version=row["version"], applied_at=row["applied_at"]) for row in rows]

    def upsert_site(self, spec: SiteSpec, tenant_id: str = "default") -> SiteRecord:
        now = _now()
        existing = self.get_site(spec.site.name)
        created_at = existing.created_at if existing else now
        tenant = existing.tenant_id if existing else tenant_id
        payload = spec.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sites (name, tenant_id, spec_json, platform, hardware_provider, nodes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    tenant_id=sites.tenant_id,
                    spec_json=excluded.spec_json,
                    platform=excluded.platform,
                    hardware_provider=excluded.hardware_provider,
                    nodes=excluded.nodes,
                    updated_at=excluded.updated_at
                """,
                (
                    spec.site.name,
                    tenant,
                    json.dumps(payload),
                    spec.platform.type.value,
                    spec.hardware.vendor,
                    len(spec.hardware.nodes),
                    created_at,
                    now,
                ),
            )
        return self.get_site(spec.site.name)  # type: ignore[return-value]

    def list_sites(self, tenant_id: str | None = None) -> list[SiteRecord]:
        with self._connect() as conn:
            if tenant_id and tenant_id != "*":
                rows = conn.execute("SELECT * FROM sites WHERE tenant_id = ? ORDER BY name", (tenant_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sites ORDER BY name").fetchall()
        return [self._site_from_row(row) for row in rows]

    def get_site(self, name: str, tenant_id: str | None = None) -> SiteRecord | None:
        with self._connect() as conn:
            if tenant_id and tenant_id != "*":
                row = conn.execute("SELECT * FROM sites WHERE name = ? AND tenant_id = ?", (name, tenant_id)).fetchone()
            else:
                row = conn.execute("SELECT * FROM sites WHERE name = ?", (name,)).fetchone()
        return self._site_from_row(row) if row else None

    def delete_site(self, name: str, tenant_id: str | None = None) -> bool:
        with self._connect() as conn:
            if tenant_id and tenant_id != "*":
                result = conn.execute("DELETE FROM sites WHERE name = ? AND tenant_id = ?", (name, tenant_id))
            else:
                result = conn.execute("DELETE FROM sites WHERE name = ?", (name,))
        return result.rowcount > 0

    def create_job(self, site_name: str, action: str, params: dict[str, Any] | None = None) -> JobRecord:
        now = _now()
        job_id = str(uuid.uuid4())
        site = self.get_site(site_name)
        tenant_id = site.tenant_id if site else "default"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, tenant_id, site_name, action, status, params_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, tenant_id, site_name, action, "queued", json.dumps(params or {}), now),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def start_job(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET status = ?, started_at = ? WHERE id = ?", ("running", _now(), job_id))
        self.add_job_event(job_id, "info", "Job started", {"status": "running"})

    def claim_next_job(self) -> JobRecord | None:
        if self.backend == "postgres":
            return self._claim_next_job_postgres()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at LIMIT 1", ("queued",)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE jobs SET status = ?, started_at = ? WHERE id = ?", ("running", _now(), row["id"]))
        return self.get_job(row["id"])

    def _claim_next_job_postgres(self) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = ?
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE status = ?
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                ("running", _now(), "queued"),
            ).fetchone()
        return self._job_from_row(row) if row else None

    def finish_job(self, job_id: str, result: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, finished_at = ? WHERE id = ?",
                ("succeeded", json.dumps(result), _now(), job_id),
            )
        self.add_job_event(job_id, "info", "Job completed", {"status": "succeeded"})

    def fail_job(self, job_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                ("failed", error, _now(), job_id),
            )
        self.add_job_event(job_id, "error", "Job failed", {"error": error})

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self, site_name: str | None = None, tenant_id: str | None = None) -> list[JobRecord]:
        with self._connect() as conn:
            if site_name and tenant_id and tenant_id != "*":
                rows = conn.execute("SELECT * FROM jobs WHERE site_name = ? AND tenant_id = ? ORDER BY created_at DESC", (site_name, tenant_id)).fetchall()
            elif site_name:
                rows = conn.execute("SELECT * FROM jobs WHERE site_name = ? ORDER BY created_at DESC", (site_name,)).fetchall()
            elif tenant_id and tenant_id != "*":
                rows = conn.execute("SELECT * FROM jobs WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [self._job_from_row(row) for row in rows]

    def cancel_job(self, job_id: str) -> JobRecord | None:
        job = self.get_job(job_id)
        if job is None:
            return None
        if job.status in {"succeeded", "failed", "canceled"}:
            return job
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                ("canceled", "Canceled by operator", _now(), job_id),
            )
        self.add_job_event(job_id, "warning", "Job canceled by operator", {"status": "canceled"})
        return self.get_job(job_id)

    def retry_job(self, job_id: str) -> JobRecord | None:
        job = self.get_job(job_id)
        if job is None:
            return None
        return self.create_job(job.site_name, job.action, job.params)

    def save_inventory(self, report: InventoryReport) -> InventoryRecord:
        now = _now()
        payload = report.model_dump(mode="json")
        site = self.get_site(report.site_name)
        tenant_id = site.tenant_id if site else "default"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO inventory (site_name, tenant_id, report_json, reachable_nodes, total_nodes, collected_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_name) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    report_json=excluded.report_json,
                    reachable_nodes=excluded.reachable_nodes,
                    total_nodes=excluded.total_nodes,
                    collected_at=excluded.collected_at
                """,
                (
                    report.site_name,
                    tenant_id,
                    json.dumps(payload),
                    report.reachable_count,
                    len(report.nodes),
                    now,
                ),
            )
        return self.get_inventory(report.site_name)  # type: ignore[return-value]

    def get_inventory(self, site_name: str, tenant_id: str | None = None) -> InventoryRecord | None:
        with self._connect() as conn:
            if tenant_id and tenant_id != "*":
                row = conn.execute("SELECT * FROM inventory WHERE site_name = ? AND tenant_id = ?", (site_name, tenant_id)).fetchone()
            else:
                row = conn.execute("SELECT * FROM inventory WHERE site_name = ?", (site_name,)).fetchone()
        return self._inventory_from_row(row) if row else None

    def seed_access_defaults(self) -> None:
        defaults = [
            RoleRecord(
                name="Viewer",
                description="Read-only access to sites, jobs, providers, and reports.",
                permissions=["read-sites", "read-jobs", "read-providers", "read-settings", "read-inventory"],
                built_in=True,
                created_at=_now(),
                updated_at=_now(),
            ),
            RoleRecord(
                name="Operator",
                description="Runs inventory, preflight, artifact, and validation workflows.",
                permissions=["run-inventory", "run-preflight", "generate-artifacts", "run-validate", "mount-iso"],
                built_in=True,
                created_at=_now(),
                updated_at=_now(),
            ),
            RoleRecord(
                name="Deployment Admin",
                description="Creates and edits deployment desired state.",
                permissions=["create-sites", "update-sites", "delete-sites", "run-plan", "write-inventory"],
                built_in=True,
                created_at=_now(),
                updated_at=_now(),
            ),
            RoleRecord(
                name="Platform Admin",
                description="Manages providers, access posture, settings, and platform policy.",
                permissions=[
                    "read-sites",
                    "read-jobs",
                    "read-providers",
                    "read-settings",
                    "read-inventory",
                    "manage-providers",
                    "manage-settings",
                    "manage-access",
                    "read-audit",
                    "export-reports",
                    "worker-execute",
                ],
                built_in=True,
                created_at=_now(),
                updated_at=_now(),
            ),
            RoleRecord(
                name="Auditor",
                description="Reviews audit events, job history, and exported reports.",
                permissions=["read-audit", "export-reports"],
                built_in=True,
                created_at=_now(),
                updated_at=_now(),
            ),
        ]
        for role in defaults:
            existing = self.get_role(role.name)
            if existing is None or existing.built_in:
                self.upsert_role(role)

        admin = self.get_user("admin")
        if admin is None:
            self.upsert_user(
                UserRecord(
                    username="admin",
                    display_name="Platform Administrator",
                    email="admin@strataone.local",
                    tenant_id="default",
                    roles=["Platform Admin", "Deployment Admin", "Operator"],
                    status="active",
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
        elif "Operator" not in admin.roles:
            self.upsert_user(admin.model_copy(update={"roles": [*admin.roles, "Operator"]}))

    def list_roles(self) -> list[RoleRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM roles ORDER BY built_in DESC, name").fetchall()
        return [self._role_from_row(row) for row in rows]

    def get_role(self, name: str) -> RoleRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM roles WHERE name = ?", (name,)).fetchone()
        return self._role_from_row(row) if row else None

    def upsert_role(self, role: RoleRecord) -> RoleRecord:
        now = _now()
        existing = self.get_role(role.name)
        created_at = existing.created_at if existing else role.created_at or now
        built_in = existing.built_in if existing else role.built_in
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO roles (name, description, permissions_json, built_in, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    permissions_json=excluded.permissions_json,
                    built_in=roles.built_in,
                    updated_at=excluded.updated_at
                """,
                (role.name, role.description, json.dumps(role.permissions), int(built_in), created_at, now),
            )
        return self.get_role(role.name)  # type: ignore[return-value]

    def delete_role(self, name: str) -> bool:
        role = self.get_role(name)
        if role is None or role.built_in:
            return False
        users = self.list_users()
        with self._connect() as conn:
            for user in users:
                if name in user.roles:
                    remaining = [item for item in user.roles if item != name]
                    conn.execute("UPDATE users SET roles_json = ?, updated_at = ? WHERE username = ?", (json.dumps(remaining), _now(), user.username))
            result = conn.execute("DELETE FROM roles WHERE name = ?", (name,))
        return result.rowcount > 0

    def list_users(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [self._user_from_row(row) for row in rows]

    def get_user(self, username: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return self._user_from_row(row) if row else None

    def upsert_user(self, user: UserRecord, password_hash: str | None = None) -> UserRecord:
        now = _now()
        existing = self.get_user(user.username)
        created_at = existing.created_at if existing else user.created_at or now
        with self._connect() as conn:
            if password_hash is None:
                row = conn.execute("SELECT password_hash FROM users WHERE username = ?", (user.username,)).fetchone()
                password_hash = row["password_hash"] if row else None
            conn.execute(
                """
                INSERT INTO users (username, tenant_id, display_name, email, roles_json, status, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    tenant_id=excluded.tenant_id,
                    display_name=excluded.display_name,
                    email=excluded.email,
                    roles_json=excluded.roles_json,
                    status=excluded.status,
                    password_hash=excluded.password_hash,
                    updated_at=excluded.updated_at
                """,
                (user.username, user.tenant_id, user.display_name, user.email, json.dumps(user.roles), user.status, password_hash, created_at, now),
            )
        return self.get_user(user.username)  # type: ignore[return-value]

    def delete_user(self, username: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        return result.rowcount > 0

    def get_user_password_hash(self, username: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE username = ?", (username,)).fetchone()
        return row["password_hash"] if row and row["password_hash"] else None

    def create_session(self, token_hash: str, username: str, expires_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token_hash, username, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(token_hash) DO UPDATE SET
                    username=excluded.username,
                    expires_at=excluded.expires_at
                """,
                (token_hash, username, _now(), expires_at),
            )

    def get_session_user(self, token_hash: str, now: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT username FROM sessions WHERE token_hash = ? AND expires_at > ?", (token_hash, now)).fetchone()
        return self.get_user(row["username"]) if row else None

    def revoke_session(self, token_hash: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        return result.rowcount > 0

    def list_sessions(self) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [
            SessionRecord(
                token_hash=row["token_hash"],
                username=row["username"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
            )
            for row in rows
        ]

    def add_audit(self, actor: str, action: str, resource: str, detail: dict[str, Any] | None = None) -> AuditRecord:
        audit_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (id, actor, action, resource, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (audit_id, actor, action, resource, json.dumps(detail or {}), now),
            )
        return AuditRecord(id=audit_id, actor=actor, action=action, resource=resource, detail=detail or {}, created_at=now)

    def list_audit(self, limit: int = 100) -> list[AuditRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._audit_from_row(row) for row in rows]

    def create_approval(
        self,
        site_name: str,
        action: str,
        requested_by: str,
        detail: dict[str, Any] | None = None,
        *,
        required_approvals: int = 1,
        approver_roles: list[str] | None = None,
        expires_minutes: int | None = None,
    ) -> ApprovalRecord:
        approval_id = str(uuid.uuid4())
        now = _now()
        expires_at = (datetime.now(UTC) + timedelta(minutes=max(1, expires_minutes))).isoformat() if expires_minutes else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (id, site_name, action, status, requested_by, detail_json, votes_json, required_approvals, approver_roles_json, expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    site_name,
                    action,
                    "pending",
                    requested_by,
                    json.dumps(detail or {}),
                    "[]",
                    max(1, required_approvals),
                    json.dumps(approver_roles or []),
                    expires_at,
                    now,
                    now,
                ),
            )
        return self.get_approval(approval_id)  # type: ignore[return-value]

    def approve(self, approval_id: str, approved_by: str, roles: list[str] | None = None) -> ApprovalRecord | None:
        approval = self.get_approval(approval_id)
        if approval is None:
            return None
        now = _now()
        if approval.status != "pending":
            return approval
        if approval.expires_at and approval.expires_at <= now:
            return self.expire_approval(approval_id)
        if approval.approver_roles and not set(roles or []).intersection(approval.approver_roles):
            return approval
        votes = [vote for vote in approval.votes if vote.get("actor") != approved_by]
        votes.append({"actor": approved_by, "roles": roles or [], "created_at": now})
        status = "approved" if len(votes) >= approval.required_approvals else "pending"
        approved_by_value = approved_by if status == "approved" else None
        with self._connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, approved_by = ?, votes_json = ?, updated_at = ? WHERE id = ?",
                (status, approved_by_value, json.dumps(votes), now, approval_id),
            )
        return self.get_approval(approval_id)

    def expire_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, approved_by = ?, updated_at = ? WHERE id = ? AND status = ?",
                ("expired", None, _now(), approval_id, "pending"),
            )
        return self.get_approval(approval_id)

    def expire_pending_approvals(self) -> int:
        now = _now()
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE approvals SET status = ?, updated_at = ? WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?",
                ("expired", now, "pending", now),
            )
        return result.rowcount

    def reject(self, approval_id: str, rejected_by: str, reason: str = "") -> ApprovalRecord | None:
        approval = self.get_approval(approval_id)
        if approval is None:
            return None
        detail = {**approval.detail, "rejection_reason": reason}
        with self._connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, approved_by = ?, detail_json = ?, updated_at = ? WHERE id = ?",
                ("rejected", rejected_by, json.dumps(detail), _now(), approval_id),
            )
        return self.get_approval(approval_id)

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return self._approval_from_row(row) if row else None

    def list_approvals(self) -> list[ApprovalRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
        return [self._approval_from_row(row) for row in rows]

    def upsert_approval_policy(
        self,
        action: str,
        *,
        enabled: bool = True,
        approver_roles: list[str] | None = None,
        min_approvals: int = 1,
        expires_minutes: int = 1440,
    ) -> ApprovalPolicyRecord:
        now = _now()
        existing = self.get_approval_policy(action)
        policy_id = existing.id if existing else str(uuid.uuid4())
        created_at = existing.created_at if existing else now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approval_policies (id, action, enabled, approver_roles_json, min_approvals, expires_minutes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    action=excluded.action,
                    enabled=excluded.enabled,
                    approver_roles_json=excluded.approver_roles_json,
                    min_approvals=excluded.min_approvals,
                    expires_minutes=excluded.expires_minutes,
                    updated_at=excluded.updated_at
                """,
                (policy_id, action, int(enabled), json.dumps(approver_roles or []), max(1, min_approvals), max(1, expires_minutes), created_at, now),
            )
        return self.get_approval_policy(action)  # type: ignore[return-value]

    def get_approval_policy(self, action: str) -> ApprovalPolicyRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM approval_policies WHERE action = ? ORDER BY updated_at DESC LIMIT 1", (action,)).fetchone()
        return self._approval_policy_from_row(row) if row else None

    def list_approval_policies(self) -> list[ApprovalPolicyRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM approval_policies ORDER BY action").fetchall()
        return [self._approval_policy_from_row(row) for row in rows]

    def delete_approval_policy(self, policy_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM approval_policies WHERE id = ?", (policy_id,))
        return result.rowcount > 0

    def add_job_event(self, job_id: str, level: str, message: str, detail: dict[str, Any] | None = None) -> JobEventRecord:
        event_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO job_events (id, job_id, level, message, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, job_id, level, message, json.dumps(detail or {}), now),
            )
        return JobEventRecord(id=event_id, job_id=job_id, level=level, message=message, detail=detail or {}, created_at=now)

    def list_job_events(self, job_id: str) -> list[JobEventRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM job_events WHERE job_id = ? ORDER BY created_at", (job_id,)).fetchall()
        return [self._job_event_from_row(row) for row in rows]

    def upsert_provider_config(self, provider_name: str, config: dict[str, Any]) -> ProviderConfigRecord:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_configs (provider_name, config_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(provider_name) DO UPDATE SET
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (provider_name, json.dumps(config), now),
            )
        return self.get_provider_config(provider_name)  # type: ignore[return-value]

    def get_provider_config(self, provider_name: str) -> ProviderConfigRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM provider_configs WHERE provider_name = ?", (provider_name,)).fetchone()
        return self._provider_config_from_row(row) if row else None

    def add_provider_validation(
        self,
        provider_name: str,
        operation: str,
        status: str,
        lab: str | None = None,
        evidence: str | None = None,
        notes: str | None = None,
    ) -> ProviderValidationRecord:
        record_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_validation (id, provider_name, operation, status, lab, evidence, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, provider_name, operation, status, lab, evidence, notes, now),
            )
        return ProviderValidationRecord(
            id=record_id,
            provider_name=provider_name,
            operation=operation,
            status=status,
            lab=lab,
            evidence=evidence,
            notes=notes,
            created_at=now,
        )

    def create_provider_validation_run(
        self,
        provider_name: str,
        operation: str,
        mode: str,
        status: str,
        target: str | None,
        result: dict[str, Any],
    ) -> ProviderValidationRunRecord:
        record_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_validation_runs (id, provider_name, operation, mode, status, target, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, provider_name, operation, mode, status, target, json.dumps(result), now),
            )
        return ProviderValidationRunRecord(id=record_id, provider_name=provider_name, operation=operation, mode=mode, status=status, target=target, result=result, created_at=now)

    def list_provider_validation_runs(self, provider_name: str | None = None) -> list[ProviderValidationRunRecord]:
        with self._connect() as conn:
            if provider_name:
                rows = conn.execute("SELECT * FROM provider_validation_runs WHERE provider_name = ? ORDER BY created_at DESC", (provider_name,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM provider_validation_runs ORDER BY created_at DESC").fetchall()
        return [self._provider_validation_run_from_row(row) for row in rows]

    def list_provider_validation(self, provider_name: str | None = None) -> list[ProviderValidationRecord]:
        with self._connect() as conn:
            if provider_name:
                rows = conn.execute("SELECT * FROM provider_validation WHERE provider_name = ? ORDER BY created_at DESC", (provider_name,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM provider_validation ORDER BY created_at DESC").fetchall()
        return [self._provider_validation_from_row(row) for row in rows]

    def upsert_secret_ref(self, name: str, secret_type: str, provider: str, reference: str, metadata: dict[str, Any] | None = None) -> SecretRefRecord:
        now = _now()
        existing = self.get_secret_ref(name)
        created_at = existing.created_at if existing else now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO secret_refs (name, type, provider, reference, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    type=excluded.type,
                    provider=excluded.provider,
                    reference=excluded.reference,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (name, secret_type, provider, reference, json.dumps(metadata or {}), created_at, now),
            )
        return self.get_secret_ref(name)  # type: ignore[return-value]

    def get_secret_ref(self, name: str) -> SecretRefRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM secret_refs WHERE name = ?", (name,)).fetchone()
        return self._secret_ref_from_row(row) if row else None

    def list_secret_refs(self) -> list[SecretRefRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM secret_refs ORDER BY type, name").fetchall()
        return [self._secret_ref_from_row(row) for row in rows]

    def delete_secret_ref(self, name: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM secret_refs WHERE name = ?", (name,))
        return result.rowcount > 0

    def create_discovery_run(self, name: str, cidr: str, provider: str, result: dict[str, Any], status: str = "planned") -> DiscoveryRunRecord:
        run_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO discovery_runs (id, name, cidr, provider, status, result_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, name, cidr, provider, status, json.dumps(result), now, now),
            )
        return self.get_discovery_run(run_id)  # type: ignore[return-value]

    def update_discovery_run(self, run_id: str, status: str, result: dict[str, Any]) -> DiscoveryRunRecord | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE discovery_runs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(result), _now(), run_id),
            )
        return self.get_discovery_run(run_id)

    def get_discovery_run(self, run_id: str) -> DiscoveryRunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM discovery_runs WHERE id = ?", (run_id,)).fetchone()
        return self._discovery_run_from_row(row) if row else None

    def list_discovery_runs(self) -> list[DiscoveryRunRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM discovery_runs ORDER BY created_at DESC").fetchall()
        return [self._discovery_run_from_row(row) for row in rows]

    def delete_discovery_run(self, run_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM discovery_runs WHERE id = ?", (run_id,))
        return result.rowcount > 0

    def upsert_iso(self, name: str, uri: str, checksum: str | None = None, checksum_algorithm: str = "sha256", status: str = "registered") -> IsoRecord:
        now = _now()
        existing = self.get_iso(name)
        created_at = existing.created_at if existing else now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO iso_registry (name, uri, checksum, checksum_algorithm, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    uri=excluded.uri,
                    checksum=excluded.checksum,
                    checksum_algorithm=excluded.checksum_algorithm,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (name, uri, checksum, checksum_algorithm, status, created_at, now),
            )
        return self.get_iso(name)  # type: ignore[return-value]

    def update_iso_status(self, name: str, status: str) -> IsoRecord | None:
        with self._connect() as conn:
            conn.execute("UPDATE iso_registry SET status = ?, updated_at = ? WHERE name = ?", (status, _now(), name))
        return self.get_iso(name)

    def get_iso(self, name: str) -> IsoRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM iso_registry WHERE name = ?", (name,)).fetchone()
        return self._iso_from_row(row) if row else None

    def list_isos(self) -> list[IsoRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM iso_registry ORDER BY name").fetchall()
        return [self._iso_from_row(row) for row in rows]

    def delete_iso(self, name: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM iso_registry WHERE name = ?", (name,))
        return result.rowcount > 0

    def _site_from_row(self, row: sqlite3.Row) -> SiteRecord:
        return SiteRecord(
            name=row["name"],
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
            spec=json.loads(row["spec_json"]),
            platform=row["platform"],
            hardware_provider=row["hardware_provider"],
            nodes=row["nodes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _job_from_row(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
            site_name=row["site_name"],
            action=row["action"],
            status=row["status"],
            params=json.loads(row["params_json"]) if "params_json" in row.keys() and row["params_json"] else {},
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _inventory_from_row(self, row: sqlite3.Row) -> InventoryRecord:
        return InventoryRecord(
            site_name=row["site_name"],
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
            report=json.loads(row["report_json"]),
            reachable_nodes=row["reachable_nodes"],
            total_nodes=row["total_nodes"],
            collected_at=row["collected_at"],
        )

    def _role_from_row(self, row: sqlite3.Row) -> RoleRecord:
        return RoleRecord(
            name=row["name"],
            description=row["description"],
            permissions=json.loads(row["permissions_json"]),
            built_in=bool(row["built_in"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _user_from_row(self, row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            username=row["username"],
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
            display_name=row["display_name"],
            email=row["email"],
            roles=json.loads(row["roles_json"]),
            status=row["status"],
            password_configured=bool(row["password_hash"]) if "password_hash" in row.keys() else False,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _audit_from_row(self, row) -> AuditRecord:
        return AuditRecord(
            id=row["id"],
            actor=row["actor"],
            action=row["action"],
            resource=row["resource"],
            detail=json.loads(row["detail_json"]),
            created_at=row["created_at"],
        )

    def _approval_from_row(self, row) -> ApprovalRecord:
        return ApprovalRecord(
            id=row["id"],
            site_name=row["site_name"],
            action=row["action"],
            status=row["status"],
            requested_by=row["requested_by"],
            approved_by=row["approved_by"],
            detail=json.loads(row["detail_json"]),
            votes=json.loads(row["votes_json"]) if "votes_json" in row.keys() and row["votes_json"] else [],
            required_approvals=row["required_approvals"] if "required_approvals" in row.keys() else 1,
            approver_roles=json.loads(row["approver_roles_json"]) if "approver_roles_json" in row.keys() and row["approver_roles_json"] else [],
            expires_at=row["expires_at"] if "expires_at" in row.keys() else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _approval_policy_from_row(self, row) -> ApprovalPolicyRecord:
        return ApprovalPolicyRecord(
            id=row["id"],
            action=row["action"],
            enabled=bool(row["enabled"]),
            approver_roles=json.loads(row["approver_roles_json"]),
            min_approvals=row["min_approvals"],
            expires_minutes=row["expires_minutes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _job_event_from_row(self, row) -> JobEventRecord:
        return JobEventRecord(
            id=row["id"],
            job_id=row["job_id"],
            level=row["level"],
            message=row["message"],
            detail=json.loads(row["detail_json"]),
            created_at=row["created_at"],
        )

    def _provider_config_from_row(self, row) -> ProviderConfigRecord:
        return ProviderConfigRecord(
            provider_name=row["provider_name"],
            config=json.loads(row["config_json"]),
            updated_at=row["updated_at"],
        )

    def _provider_validation_from_row(self, row) -> ProviderValidationRecord:
        return ProviderValidationRecord(
            id=row["id"],
            provider_name=row["provider_name"],
            operation=row["operation"],
            status=row["status"],
            lab=row["lab"],
            evidence=row["evidence"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def _provider_validation_run_from_row(self, row) -> ProviderValidationRunRecord:
        return ProviderValidationRunRecord(
            id=row["id"],
            provider_name=row["provider_name"],
            operation=row["operation"],
            mode=row["mode"],
            status=row["status"],
            target=row["target"],
            result=json.loads(row["result_json"]),
            created_at=row["created_at"],
        )

    def _secret_ref_from_row(self, row) -> SecretRefRecord:
        return SecretRefRecord(
            name=row["name"],
            type=row["type"],
            provider=row["provider"],
            reference=row["reference"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _discovery_run_from_row(self, row) -> DiscoveryRunRecord:
        return DiscoveryRunRecord(
            id=row["id"],
            name=row["name"],
            cidr=row["cidr"],
            provider=row["provider"],
            status=row["status"],
            result=json.loads(row["result_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _iso_from_row(self, row) -> IsoRecord:
        return IsoRecord(
            name=row["name"],
            uri=row["uri"],
            checksum=row["checksum"],
            checksum_algorithm=row["checksum_algorithm"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def spec_from_record(record: SiteRecord) -> SiteSpec:
    return SiteSpec.model_validate(record.spec)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _postgres_sql(sql: str) -> str:
    return sql.replace("?", "%s")
