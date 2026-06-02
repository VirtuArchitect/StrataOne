from abc import ABC, abstractmethod

from strataone.plan import PlanStep
from strataone.state import PlatformType, SiteSpec


class PlatformProvider(ABC):
    name: str

    @abstractmethod
    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        """Return dry-run actions required by this platform provider."""


class AzureLocalProvider(PlatformProvider):
    name = "azure-local"

    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        return [
            PlanStep(phase="platform", action="Prepare Azure Arc registration prerequisites", provider=self.name),
            PlanStep(phase="platform", action="Register nodes and site resources with Azure Arc", provider=self.name),
            PlanStep(phase="platform", action="Deploy Azure Local instance through ARM/Bicep desired state", provider=self.name),
            PlanStep(phase="platform", action="Configure Azure Local networking, storage, and cluster topology", provider=self.name),
            PlanStep(phase="platform", action="Attach Azure Policy, Monitor, Defender, and Update Manager baselines", provider=self.name),
            *self._workload_steps(spec),
        ]

    def _workload_steps(self, spec: SiteSpec) -> list[PlanStep]:
        steps: list[PlanStep] = []
        if spec.workloads.aks:
            steps.append(PlanStep(phase="workload", action="Deploy AKS enabled by Azure Arc", provider=self.name))
        if spec.workloads.arc_vms:
            steps.append(PlanStep(phase="workload", action="Enable Arc VM management", provider=self.name))
        if spec.workloads.avd:
            steps.append(PlanStep(phase="workload", action="Prepare Azure Virtual Desktop host capacity", provider=self.name))
        return steps


class VMwareVsphereProvider(PlatformProvider):
    name = "vmware-vsphere"

    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        return [
            PlanStep(phase="platform", action="Install or validate ESXi hosts", provider=self.name),
            PlanStep(phase="platform", action="Register hosts with vCenter", provider=self.name),
            PlanStep(phase="platform", action="Configure cluster, networking, storage, and lifecycle baselines", provider=self.name),
        ]


class NutanixAhvProvider(PlatformProvider):
    name = "nutanix-ahv"

    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        return [
            PlanStep(phase="platform", action="Image nodes and form Nutanix AHV cluster", provider=self.name),
            PlanStep(phase="platform", action="Register cluster with Prism Central", provider=self.name),
            PlanStep(phase="platform", action="Apply storage, networking, LCM, and policy baselines", provider=self.name),
        ]


class ProxmoxProvider(PlatformProvider):
    name = "proxmox"

    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        return [
            PlanStep(phase="platform", action="Install Proxmox VE and join cluster nodes", provider=self.name),
            PlanStep(phase="platform", action="Configure Linux bridge or SDN networking", provider=self.name),
            PlanStep(phase="platform", action="Configure local, shared, or Ceph-backed storage", provider=self.name),
        ]


class GenericPlatformProvider(PlatformProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        return [
            PlanStep(phase="platform", action=f"Validate provider contract for {self.name}", provider=self.name),
            PlanStep(phase="platform", action=f"Deploy {self.name} platform using provider-specific extension", provider=self.name),
        ]


def get_platform_provider(platform_type: PlatformType) -> PlatformProvider:
    providers: dict[PlatformType, PlatformProvider] = {
        PlatformType.AZURE_LOCAL: AzureLocalProvider(),
        PlatformType.VMWARE_VSPHERE: VMwareVsphereProvider(),
        PlatformType.NUTANIX_AHV: NutanixAhvProvider(),
        PlatformType.PROXMOX: ProxmoxProvider(),
    }
    return providers.get(platform_type, GenericPlatformProvider(platform_type.value))
