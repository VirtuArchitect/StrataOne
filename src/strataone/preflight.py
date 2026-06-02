from enum import StrEnum

from pydantic import BaseModel

from strataone.inventory import InventoryReport
from strataone.state import PlatformType, SiteSpec


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class PreflightCheck(BaseModel):
    category: str
    name: str
    status: CheckStatus
    message: str


class PreflightReport(BaseModel):
    site_name: str
    ready: bool
    checks: list[PreflightCheck]

    @property
    def pass_count(self) -> int:
        return sum(1 for check in self.checks if check.status == CheckStatus.PASS)

    @property
    def warn_count(self) -> int:
        return sum(1 for check in self.checks if check.status == CheckStatus.WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for check in self.checks if check.status == CheckStatus.FAIL)


class PreflightRunner:
    def run(self, spec: SiteSpec, inventory: InventoryReport | None = None) -> PreflightReport:
        checks = [
            *self._desired_state_checks(spec),
            *self._platform_checks(spec),
            *self._inventory_checks(spec, inventory),
        ]
        ready = all(check.status != CheckStatus.FAIL for check in checks)
        return PreflightReport(site_name=spec.site.name, ready=ready, checks=checks)

    def _desired_state_checks(self, spec: SiteSpec) -> list[PreflightCheck]:
        checks = [
            self._check(
                "desired-state",
                "node-count",
                CheckStatus.PASS if len(spec.hardware.nodes) > 0 else CheckStatus.FAIL,
                f"{len(spec.hardware.nodes)} node(s) declared",
            ),
            self._check(
                "network",
                "management-vlan",
                CheckStatus.PASS if spec.network.management_vlan > 0 else CheckStatus.FAIL,
                f"management VLAN {spec.network.management_vlan}",
            ),
        ]

        if spec.network.dns_servers:
            checks.append(self._check("network", "dns", CheckStatus.PASS, f"{len(spec.network.dns_servers)} DNS server(s) declared"))
        else:
            checks.append(self._check("network", "dns", CheckStatus.WARN, "no DNS servers declared"))

        if spec.network.ntp_servers:
            checks.append(self._check("network", "ntp", CheckStatus.PASS, f"{len(spec.network.ntp_servers)} NTP server(s) declared"))
        else:
            checks.append(self._check("network", "ntp", CheckStatus.WARN, "no NTP servers declared"))

        serials = [node.serial for node in spec.hardware.nodes]
        checks.append(
            self._check(
                "desired-state",
                "unique-serials",
                CheckStatus.PASS if len(serials) == len(set(serials)) else CheckStatus.FAIL,
                "hardware serials are unique" if len(serials) == len(set(serials)) else "duplicate hardware serials found",
            )
        )
        return checks

    def _platform_checks(self, spec: SiteSpec) -> list[PreflightCheck]:
        if spec.platform.type != PlatformType.AZURE_LOCAL:
            return [
                self._check(
                    "platform",
                    "provider",
                    CheckStatus.PASS,
                    f"{spec.platform.type.value} provider selected",
                )
            ]

        checks = [
            self._check("platform", "provider", CheckStatus.PASS, "Azure Local provider selected"),
            self._check(
                "platform",
                "topology",
                CheckStatus.PASS if spec.platform.topology else CheckStatus.WARN,
                spec.platform.topology or "no Azure Local topology declared",
            ),
        ]
        azure = spec.platform.azure
        for field_name in ("subscription_id", "resource_group", "region"):
            value = getattr(azure, field_name) if azure else None
            checks.append(
                self._check(
                    "azure",
                    field_name,
                    CheckStatus.PASS if value else CheckStatus.FAIL,
                    str(value) if value else f"missing Azure {field_name}",
                )
            )
        return checks

    def _inventory_checks(self, spec: SiteSpec, inventory: InventoryReport | None) -> list[PreflightCheck]:
        if inventory is None:
            return [
                self._check(
                    "inventory",
                    "redfish",
                    CheckStatus.WARN,
                    "inventory not collected; set BMC credentials to run reachability checks",
                )
            ]

        expected_serials = {node.serial for node in spec.hardware.nodes}
        observed_serials = {node.serial for node in inventory.nodes}
        checks = [
            self._check(
                "inventory",
                "node-count",
                CheckStatus.PASS if len(inventory.nodes) == len(spec.hardware.nodes) else CheckStatus.FAIL,
                f"{len(inventory.nodes)}/{len(spec.hardware.nodes)} node inventory record(s)",
            ),
            self._check(
                "inventory",
                "serial-match",
                CheckStatus.PASS if expected_serials == observed_serials else CheckStatus.FAIL,
                "inventory serials match desired state" if expected_serials == observed_serials else "inventory serials do not match desired state",
            ),
        ]

        for node in inventory.nodes:
            checks.append(
                self._check(
                    "inventory",
                    f"{node.serial}-bmc",
                    CheckStatus.PASS if node.reachable else CheckStatus.FAIL,
                    f"{node.bmc_ip} reachable" if node.reachable else node.error or f"{node.bmc_ip} unreachable",
                )
            )
            if node.reachable:
                checks.append(
                    self._check(
                        "inventory",
                        f"{node.serial}-firmware",
                        CheckStatus.PASS if node.firmware else CheckStatus.WARN,
                        f"{len(node.firmware)} firmware item(s)" if node.firmware else "firmware inventory unavailable",
                    )
                )
        return checks

    def _check(self, category: str, name: str, status: CheckStatus, message: str) -> PreflightCheck:
        return PreflightCheck(category=category, name=name, status=status, message=message)
