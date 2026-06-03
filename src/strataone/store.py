import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from strataone.inventory import InventoryReport
from strataone.state import SiteSpec


class SiteRecord(BaseModel):
    name: str
    spec: dict[str, Any]
    platform: str
    hardware_provider: str
    nodes: int
    created_at: str
    updated_at: str


class JobRecord(BaseModel):
    id: str
    site_name: str
    action: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class InventoryRecord(BaseModel):
    site_name: str
    report: dict[str, Any]
    reachable_nodes: int
    total_nodes: int
    collected_at: str


class StrataStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.getenv("STRATAONE_DB", ".strataone/strataone.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sites (
                    name TEXT PRIMARY KEY,
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
                    site_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
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
                    report_json TEXT NOT NULL,
                    reachable_nodes INTEGER NOT NULL,
                    total_nodes INTEGER NOT NULL,
                    collected_at TEXT NOT NULL
                )
                """
            )

    def upsert_site(self, spec: SiteSpec) -> SiteRecord:
        now = _now()
        existing = self.get_site(spec.site.name)
        created_at = existing.created_at if existing else now
        payload = spec.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sites (name, spec_json, platform, hardware_provider, nodes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    spec_json=excluded.spec_json,
                    platform=excluded.platform,
                    hardware_provider=excluded.hardware_provider,
                    nodes=excluded.nodes,
                    updated_at=excluded.updated_at
                """,
                (
                    spec.site.name,
                    json.dumps(payload),
                    spec.platform.type.value,
                    spec.hardware.vendor,
                    len(spec.hardware.nodes),
                    created_at,
                    now,
                ),
            )
        return self.get_site(spec.site.name)  # type: ignore[return-value]

    def list_sites(self) -> list[SiteRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sites ORDER BY name").fetchall()
        return [self._site_from_row(row) for row in rows]

    def get_site(self, name: str) -> SiteRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sites WHERE name = ?", (name,)).fetchone()
        return self._site_from_row(row) if row else None

    def delete_site(self, name: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM sites WHERE name = ?", (name,))
        return result.rowcount > 0

    def create_job(self, site_name: str, action: str) -> JobRecord:
        now = _now()
        job_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, site_name, action, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, site_name, action, "queued", now),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def start_job(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET status = ?, started_at = ? WHERE id = ?", ("running", _now(), job_id))

    def finish_job(self, job_id: str, result: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result_json = ?, finished_at = ? WHERE id = ?",
                ("succeeded", json.dumps(result), _now(), job_id),
            )

    def fail_job(self, job_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                ("failed", error, _now(), job_id),
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(self, site_name: str | None = None) -> list[JobRecord]:
        with self._connect() as conn:
            if site_name:
                rows = conn.execute("SELECT * FROM jobs WHERE site_name = ? ORDER BY created_at DESC", (site_name,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [self._job_from_row(row) for row in rows]

    def save_inventory(self, report: InventoryReport) -> InventoryRecord:
        now = _now()
        payload = report.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO inventory (site_name, report_json, reachable_nodes, total_nodes, collected_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(site_name) DO UPDATE SET
                    report_json=excluded.report_json,
                    reachable_nodes=excluded.reachable_nodes,
                    total_nodes=excluded.total_nodes,
                    collected_at=excluded.collected_at
                """,
                (
                    report.site_name,
                    json.dumps(payload),
                    report.reachable_count,
                    len(report.nodes),
                    now,
                ),
            )
        return self.get_inventory(report.site_name)  # type: ignore[return-value]

    def get_inventory(self, site_name: str) -> InventoryRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM inventory WHERE site_name = ?", (site_name,)).fetchone()
        return self._inventory_from_row(row) if row else None

    def _site_from_row(self, row: sqlite3.Row) -> SiteRecord:
        return SiteRecord(
            name=row["name"],
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
            site_name=row["site_name"],
            action=row["action"],
            status=row["status"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _inventory_from_row(self, row: sqlite3.Row) -> InventoryRecord:
        return InventoryRecord(
            site_name=row["site_name"],
            report=json.loads(row["report_json"]),
            reachable_nodes=row["reachable_nodes"],
            total_nodes=row["total_nodes"],
            collected_at=row["collected_at"],
        )


def spec_from_record(record: SiteRecord) -> SiteSpec:
    return SiteSpec.model_validate(record.spec)


def _now() -> str:
    return datetime.now(UTC).isoformat()
