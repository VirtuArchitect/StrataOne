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
from strataone.secrets import resolve_bmc_credentials, resolve_bmc_credentials_from_ref
from strataone.store import StrataStore, spec_from_record
from strataone.validation import live_operation_allowed


INLINE_CREDENTIAL_ACTIONS = {"inventory", "mount-iso", "eject-iso"}
INLINE_CREDENTIAL_FIELDS = {"username", "password"}


class JobRunner:
    def __init__(self, store: StrataStore, max_workers: int = 4) -> None:
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._volatile_params: dict[str, dict[str, Any]] = {}

    def submit(self, site_name: str, action: str, params: dict[str, Any] | None = None) -> str:
        raw_params = params or {}
        execution_mode = os.getenv("STRATAONE_EXECUTION_MODE", "inline").lower()
        if execution_mode == "queued" and _uses_inline_credentials(action, raw_params):
            raise ValueError(f"{action} queued jobs require credential_ref or an environment/file/Vault secret provider")
        job = self.store.create_job(site_name, action, raw_params)
        queue = get_job_queue()
        if execution_mode == "inline":
            self._volatile_params[job.id] = raw_params
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
            self.store.add_job_event(job_id, "info", f"Executing {job.action}", {"site": spec.site.name})
            params = {**job.params, **self._volatile_params.pop(job_id, {}), "_job_id": job_id}
            result = self._execute(job.action, spec, params)
            self.store.finish_job(job_id, result)
        except Exception as exc:
            self.store.fail_job(job_id, str(exc))

    def _execute(self, action: str, spec, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if params.get("resume_from_job_id"):
            self.store.add_job_event(params.get("_job_id", "unknown"), "info", "Resuming from prior job", {"resume_from_job_id": params["resume_from_job_id"]})
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
        if action == "eject-iso":
            return self._eject_iso(spec, params)
        if action == "deploy-azure-local":
            return self._deploy_azure_local(spec, params)
        if action == "drift-detect":
            return self._drift_detect(spec, params)
        if action == "node-replacement":
            return self._node_replacement(spec, params)
        raise ValueError(f"unsupported job action {action}")

    def _inventory(self, spec, params: dict[str, Any]):
        secret = self._credentials(spec.site.name, params)
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
        iso_ref = params.get("iso_ref")
        iso = self.store.get_iso(str(iso_ref)) if iso_ref else None
        iso_url = params.get("iso_url") or (iso.uri if iso else None)
        if not iso_url:
            raise ValueError("iso_url is required to mount virtual media")
        secret = self._credentials(spec.site.name, params)
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

    def _eject_iso(self, spec, params: dict[str, Any]) -> dict[str, Any]:
        secret = self._credentials(spec.site.name, params)
        if secret is None:
            raise ValueError("BMC credentials are required for ISO eject jobs")
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
                    "result": client.eject_virtual_media(node),
                }
                for node in spec.hardware.nodes
            ]
            mode = "live-redfish"
        else:
            nodes = [
                {
                    "serial": node.serial,
                    "bmc_ip": node.bmc_ip,
                    "status": "planned",
                    "provider": spec.hardware.vendor,
                    "operation": "eject virtual media and clear boot override",
                }
                for node in spec.hardware.nodes
            ]
            mode = "simulated-redfish-contract"
        return {"site_name": spec.site.name, "action": "eject-iso", "nodes": nodes, "execution_mode": mode}

    def _deploy_azure_local(self, spec, params: dict[str, Any]) -> dict[str, Any]:
        if spec.platform.type.value != "azure-local":
            raise ValueError("deploy-azure-local is only supported for Azure Local sites")
        stages = [
            self._stage("validate-prerequisites", "Validate Azure tenant, subscription, resource group, region, and node count", "succeeded"),
            self._stage("prepare-arc", "Prepare Azure Arc onboarding package and service principal contract", "succeeded"),
            self._stage("register-nodes", "Register target nodes as Arc-connected machines", "ready"),
            self._stage("deploy-arm", "Deploy Azure Local resource model through ARM/Bicep desired state", "ready"),
            self._stage("configure-cluster", "Configure topology, networking, storage, and witness settings", "ready"),
            self._stage("attach-governance", "Attach Azure Policy, Monitor, Defender, and Update Manager baselines", "ready"),
        ]
        for stage in stages:
            self.store.add_job_event(params.get("_job_id", "unknown"), "info", stage["name"], {"status": stage["status"]})
        return {
            "site_name": spec.site.name,
            "action": "deploy-azure-local",
            "execution_mode": "staged-provider-contract",
            "approval_id": params.get("approval_id"),
            "azure": spec.platform.azure.model_dump(mode="json") if spec.platform.azure else {},
            "stages": stages,
            "next_actions": [
                "Confirm provider credentials and Azure permissions.",
                "Run preflight and resolve warnings.",
                "Approve live deployment action before provider execution.",
            ],
            "note": "Stages are ready for live Azure execution once provider credentials, approvals, and lab validation are configured.",
        }

    def _drift_detect(self, spec, params: dict[str, Any]) -> dict[str, Any]:
        inventory = self.store.get_inventory(spec.site.name)
        desired_nodes = {node.serial: node for node in spec.hardware.nodes}
        observed_nodes = {node.get("serial"): node for node in (inventory.report.get("nodes", []) if inventory else []) if node.get("serial")}
        missing = [serial for serial in desired_nodes if serial not in observed_nodes]
        unexpected = [serial for serial in observed_nodes if serial not in desired_nodes]
        unreachable = [serial for serial, node in observed_nodes.items() if not node.get("reachable", False)]
        checks = [
            {"name": "desired-state-registered", "status": "pass", "detail": "Site desired state is present"},
            {
                "name": "inventory-current",
                "status": "pass" if inventory else "warn",
                "detail": "Inventory is available" if inventory else "No inventory collected yet",
            },
            {"name": "node-count", "status": "pass" if not missing and not unexpected else "fail", "detail": f"{len(spec.hardware.nodes)} desired nodes, {len(observed_nodes)} observed nodes"},
            {"name": "platform", "status": "pass", "detail": spec.platform.type.value},
        ]
        for serial in missing:
            checks.append({"name": "missing-node", "status": "fail", "detail": serial})
        for serial in unexpected:
            checks.append({"name": "unexpected-node", "status": "warn", "detail": serial})
        for serial in unreachable:
            checks.append({"name": "unreachable-node", "status": "fail", "detail": serial})
        drift = [check for check in checks if check["status"] != "pass"]
        self.store.add_job_event(params.get("_job_id", "unknown"), "info", "Drift comparison complete", {"drift_items": len(drift)})
        return {
            "site_name": spec.site.name,
            "action": "drift-detect",
            "drift_detected": bool(drift),
            "checks": checks,
            "diff": {
                "missing_nodes": missing,
                "unexpected_nodes": unexpected,
                "unreachable_nodes": unreachable,
            },
            "recommendation": "Run inventory before remediation" if drift else "No drift found in current control plane data",
        }

    def _node_replacement(self, spec, params: dict[str, Any]) -> dict[str, Any]:
        failed_serial = params.get("failed_serial") or spec.hardware.nodes[0].serial
        replacement_serial = params.get("replacement_serial") or "replacement-node"
        stages = [
            self._stage("validate-replacement", f"Validate replacement node {replacement_serial}", "ready"),
            self._stage("drain-workloads", f"Drain workloads from failed node {failed_serial}", "ready"),
            self._stage("evict-node", f"Remove failed node {failed_serial} from cluster membership", "ready"),
            self._stage("image-node", "Apply platform image and bootstrap configuration", "ready"),
            self._stage("join-cluster", "Join replacement node and restore baseline", "ready"),
            self._stage("verify-health", "Run inventory, drift detection, and cluster health checks", "ready"),
        ]
        for stage in stages:
            self.store.add_job_event(params.get("_job_id", "unknown"), "info", stage["name"], {"status": stage["status"]})
        return {
            "site_name": spec.site.name,
            "action": "node-replacement",
            "failed_serial": failed_serial,
            "replacement_serial": replacement_serial,
            "stages": stages,
            "operator_inputs": {
                "failed_serial": failed_serial,
                "replacement_serial": replacement_serial,
                "credential_ref": params.get("credential_ref"),
            },
            "execution_mode": "guided-lifecycle-contract",
        }

    def _stage(self, name: str, description: str, status: str) -> dict[str, str]:
        return {"name": name, "description": description, "status": status}

    def _credentials(self, site_name: str, params: dict[str, Any]):
        if params.get("credential_ref"):
            secret = self.store.get_secret_ref(str(params["credential_ref"]))
            resolved = resolve_bmc_credentials_from_ref(secret)
            if resolved is not None:
                return resolved
        return resolve_bmc_credentials(site_name, params)


def _uses_inline_credentials(action: str, params: dict[str, Any]) -> bool:
    if action not in INLINE_CREDENTIAL_ACTIONS or params.get("credential_ref"):
        return False
    return any(params.get(field) for field in INLINE_CREDENTIAL_FIELDS)
