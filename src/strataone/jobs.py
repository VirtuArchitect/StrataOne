from concurrent.futures import ThreadPoolExecutor
import os
from typing import Any

from strataone.artifacts import ArtifactGenerator
from strataone.inventory import InventoryReport
from strataone.orchestrator import Orchestrator
from strataone.preflight import PreflightRunner
from strataone.providers.hardware import get_hardware_provider
from strataone.queue import get_job_queue
from strataone.redfish import RedfishClient, RedfishCredentials
from strataone.secrets import resolve_bmc_credentials
from strataone.store import StrataStore, spec_from_record
from strataone.validation import live_operation_allowed


class JobRunner:
    def __init__(self, store: StrataStore, max_workers: int = 4) -> None:
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, site_name: str, action: str, params: dict[str, Any] | None = None) -> str:
        job = self.store.create_job(site_name, action, params or {})
        execution_mode = os.getenv("STRATAONE_EXECUTION_MODE", "inline").lower()
        queue = get_job_queue()
        if execution_mode == "inline":
            self.executor.submit(self._run, job.id)
        elif queue is not None:
            queue.enqueue(job.id)
        return job.id

    def run_queued_once(self) -> str | None:
        queue = get_job_queue()
        if queue is not None:
            job_id = queue.dequeue()
            if job_id is None:
                return None
            self._run(job_id)
            return job_id
        job = self.store.claim_next_job()
        if job is None:
            return None
        self._run(job.id, already_started=True)
        return job.id

    def _run(self, job_id: str, already_started: bool = False) -> None:
        job = self.store.get_job(job_id)
        if job is None:
            return
        if not already_started:
            self.store.start_job(job_id)
        try:
            site = self.store.get_site(job.site_name)
            if site is None:
                raise ValueError(f"site {job.site_name} not found")
            spec = spec_from_record(site)
            result = self._execute(job.action, spec, job.params)
            self.store.finish_job(job_id, result)
        except Exception as exc:
            self.store.fail_job(job_id, str(exc))

    def _execute(self, action: str, spec, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if action == "validate":
            return {
                "valid": True,
                "site_name": spec.site.name,
                "platform": spec.platform.type.value,
                "hardware_provider": spec.hardware.vendor,
                "nodes": len(spec.hardware.nodes),
            }
        if action == "plan":
            return Orchestrator().plan(spec).model_dump(mode="json")
        if action == "inventory":
            report = self._inventory(spec, params)
            self.store.save_inventory(report)
            return report.model_dump(mode="json")
        if action == "preflight":
            inventory = self.store.get_inventory(spec.site.name)
            report = InventoryReport.model_validate(inventory.report) if inventory else None
            return PreflightRunner().run(spec, report).model_dump(mode="json")
        if action == "artifacts":
            return ArtifactGenerator().generate(spec).model_dump(mode="json")
        if action == "mount-iso":
            return self._mount_iso(spec, params)
        raise ValueError(f"unsupported job action {action}")

    def _inventory(self, spec, params: dict[str, Any]):
        secret = resolve_bmc_credentials(spec.site.name, params)
        if secret is None:
            raise ValueError("BMC credentials are required for inventory jobs")
        provider = get_hardware_provider(spec.hardware.vendor)
        insecure = params.get("insecure")
        if insecure is None:
            insecure = os.getenv("STRATAONE_BMC_INSECURE", "").lower() in {"1", "true", "yes"}
        return provider.inventory(
            spec,
            RedfishCredentials(username=secret.username, password=secret.password),
            timeout=float(params.get("timeout") or os.getenv("STRATAONE_BMC_TIMEOUT", "10")),
            verify_tls=not bool(insecure),
        )

    def _mount_iso(self, spec, params: dict[str, Any]) -> dict[str, Any]:
        iso_url = params.get("iso_url")
        if not iso_url:
            raise ValueError("iso_url is required to mount virtual media")
        secret = resolve_bmc_credentials(spec.site.name, params)
        if secret is None:
            raise ValueError("BMC credentials are required for ISO mount jobs")
        live = os.getenv("STRATAONE_ENABLE_LIVE_REDFISH", "false").lower() in {"1", "true", "yes", "on"}
        insecure = params.get("insecure")
        if insecure is None:
            insecure = os.getenv("STRATAONE_BMC_INSECURE", "").lower() in {"1", "true", "yes"}
        if live:
            if not live_operation_allowed(spec.hardware.vendor, "redfish-virtual-media"):
                raise ValueError(f"live Redfish virtual media is not lab-validated for provider {spec.hardware.vendor}")
            client = RedfishClient(
                RedfishCredentials(username=secret.username, password=secret.password),
                timeout=float(params.get("timeout") or os.getenv("STRATAONE_BMC_TIMEOUT", "10")),
                verify_tls=not bool(insecure),
            )
            nodes = [
                {
                    "serial": node.serial,
                    "bmc_ip": node.bmc_ip,
                    "status": "succeeded",
                    "provider": spec.hardware.vendor,
                    "result": client.mount_virtual_media(node, str(iso_url), boot_once=bool(params.get("boot_once", True))),
                }
                for node in spec.hardware.nodes
            ]
            return {
                "site_name": spec.site.name,
                "action": "mount-iso",
                "iso_url": str(iso_url),
                "boot_once": bool(params.get("boot_once", True)),
                "nodes": nodes,
                "execution_mode": "live-redfish",
            }
        return {
            "site_name": spec.site.name,
            "action": "mount-iso",
            "iso_url": str(iso_url),
            "boot_once": bool(params.get("boot_once", True)),
            "nodes": [
                {
                    "serial": node.serial,
                    "bmc_ip": node.bmc_ip,
                    "status": "planned",
                    "provider": spec.hardware.vendor,
                    "operation": "mount virtual media and set boot override",
                }
                for node in spec.hardware.nodes
            ],
            "execution_mode": "simulated-redfish-contract",
            "note": "Provider-specific InsertMedia/BootSourceOverride execution should be enabled behind approval gates.",
        }
