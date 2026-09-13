import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strataone.artifacts import ArtifactGenerator
from strataone.state import PlatformType, SiteSpec


AZURE_LOCAL_REQUIRED_CONFIG = ("tenant_id", "subscription_id", "resource_group", "region", "credential_ref")


class AzureLocalExecutionContract:
    """Build the first safe Azure Local provider handoff without live mutation."""

    def __init__(self, artifact_generator: ArtifactGenerator | None = None) -> None:
        self.artifact_generator = artifact_generator or ArtifactGenerator()

    def prepare(self, spec: SiteSpec, provider_config: dict[str, Any] | None, approval_id: str | None = None) -> dict[str, Any]:
        if spec.platform.type != PlatformType.AZURE_LOCAL:
            raise ValueError("deploy-azure-local is only supported for Azure Local sites")

        config = self._merged_config(spec, provider_config or {})
        missing = [field for field in AZURE_LOCAL_REQUIRED_CONFIG if not config.get(field)]
        bundle = self.artifact_generator.generate(spec)
        stages = self._stages(spec, config, missing)
        status = "ready-for-provider-handoff" if not missing else "blocked-missing-provider-config"
        manifest = {
            "generated_at": datetime.now(UTC).isoformat(),
            "site_name": spec.site.name,
            "approval_id": approval_id,
            "provider": "azure-local",
            "status": status,
            "missing_provider_config": missing,
            "azure": {key: value for key, value in config.items() if key != "credential_ref"},
            "credential_ref": config.get("credential_ref"),
            "artifact_files": bundle.files,
            "stages": stages,
        }
        manifest_path = Path(bundle.output_dir) / "azure-local-execution-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "site_name": spec.site.name,
            "action": "deploy-azure-local",
            "execution_mode": "azure-local-provider-handoff",
            "approval_id": approval_id,
            "status": status,
            "provider_configured": not missing,
            "missing_provider_config": missing,
            "azure": manifest["azure"],
            "artifact_bundle": {
                "output_dir": bundle.output_dir,
                "files": [*bundle.files, str(manifest_path)],
            },
            "stages": stages,
            "next_actions": self._next_actions(missing),
            "note": "This stage prepares reviewed Azure Local provider artifacts and evidence; live Azure mutation remains gated for a later validated provider adapter.",
        }

    def _merged_config(self, spec: SiteSpec, provider_config: dict[str, Any]) -> dict[str, Any]:
        azure = spec.platform.azure
        return {
            "tenant_id": provider_config.get("tenant_id") or (azure.tenant_id if azure else None),
            "subscription_id": provider_config.get("subscription_id") or (azure.subscription_id if azure else None),
            "resource_group": provider_config.get("resource_group") or (azure.resource_group if azure else None),
            "region": provider_config.get("region") or (azure.region if azure else None),
            "credential_ref": provider_config.get("credential_ref"),
            "cluster_name": provider_config.get("cluster_name") or spec.platform.cluster_name or spec.site.name,
            "topology": spec.platform.topology,
        }

    def _stages(self, spec: SiteSpec, config: dict[str, Any], missing: list[str]) -> list[dict[str, str]]:
        config_status = "succeeded" if not missing else "blocked"
        return [
            {
                "name": "validate-provider-config",
                "description": "Validate Azure tenant, subscription, resource group, region, and credential reference",
                "status": config_status,
            },
            {
                "name": "generate-provider-artifacts",
                "description": "Generate Azure Local parameters, Bicep, Terraform handoff, and Arc registration review script",
                "status": "succeeded",
            },
            {
                "name": "prepare-arc-registration",
                "description": f"Prepare Arc registration handoff for {len(spec.hardware.nodes)} node(s) in {config.get('resource_group') or '<resource-group>'}",
                "status": "ready" if not missing else "waiting-for-config",
            },
            {
                "name": "deploy-resource-model",
                "description": f"Prepare Azure Local resource model for cluster {config.get('cluster_name')}",
                "status": "ready" if not missing else "waiting-for-config",
            },
            {
                "name": "configure-cluster-baseline",
                "description": "Prepare topology, networking, storage, policy, monitoring, and update-management baseline handoff",
                "status": "ready" if not missing else "waiting-for-config",
            },
        ]

    def _next_actions(self, missing: list[str]) -> list[str]:
        if missing:
            return [
                f"Save Azure Local provider configuration with: {', '.join(missing)}.",
                "Retry deploy-azure-local after approval once provider configuration is complete.",
                "Keep live Azure mutation disabled until the provider adapter has lab validation evidence.",
            ]
        return [
            "Review generated Azure Local artifacts and execution manifest.",
            "Validate provider credentials and Azure role assignments outside StrataOne.",
            "Promote the next slice to a lab-validated live Azure provider adapter behind approvals.",
        ]
