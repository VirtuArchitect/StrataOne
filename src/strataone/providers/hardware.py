from abc import ABC, abstractmethod

from strataone.plan import PlanStep
from strataone.state import SiteSpec


class HardwareProvider(ABC):
    name: str

    @abstractmethod
    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        """Return dry-run actions required by this hardware provider."""


class GenericRedfishProvider(HardwareProvider):
    name = "generic-redfish"

    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        return [
            PlanStep(phase="hardware", action="Discover nodes through Redfish", provider=self.name),
            PlanStep(phase="hardware", action="Collect BMC, BIOS, firmware, disk, and NIC inventory", provider=self.name),
            PlanStep(phase="hardware", action="Apply baseline BIOS and boot profile", provider=self.name),
            PlanStep(phase="hardware", action="Mount provisioning media through virtual media", provider=self.name),
            PlanStep(phase="hardware", action="Reboot nodes into provisioning workflow", provider=self.name),
        ]


class OemHardwareProvider(GenericRedfishProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    def plan(self, spec: SiteSpec) -> list[PlanStep]:
        return [
            PlanStep(phase="hardware", action="Discover nodes through OEM management API", provider=self.name),
            PlanStep(phase="hardware", action="Apply OEM firmware, BIOS, storage, and NIC baseline", provider=self.name),
            PlanStep(phase="hardware", action="Fall back to Redfish-compatible virtual media workflow", provider=self.name),
        ]


def get_hardware_provider(name: str) -> HardwareProvider:
    normalized = name.lower()
    if normalized == "generic-redfish":
        return GenericRedfishProvider()
    if normalized in {"dell-idrac", "hpe-ilo", "lenovo-xclarity", "supermicro-redfish", "cisco-intersight"}:
        return OemHardwareProvider(normalized)
    return GenericRedfishProvider()
