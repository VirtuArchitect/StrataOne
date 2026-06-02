from pathlib import Path

from strataone.inventory import InventoryReport, NodeInventory
from strataone.preflight import CheckStatus, PreflightRunner
from strataone.state import load_site_spec


def test_preflight_warns_when_inventory_is_not_collected() -> None:
    spec = load_site_spec(Path("examples/azure-local-branch.yaml"))

    report = PreflightRunner().run(spec)

    assert report.ready is True
    assert any(check.status == CheckStatus.WARN and check.name == "redfish" for check in report.checks)


def test_preflight_fails_when_bmc_is_unreachable() -> None:
    spec = load_site_spec(Path("examples/azure-local-branch.yaml"))
    inventory = InventoryReport(
        site_name=spec.site.name,
        provider="generic-redfish",
        nodes=[
            NodeInventory(serial="ABC123", bmc_ip="10.10.1.11", reachable=False, error="timeout"),
            NodeInventory(serial="ABC124", bmc_ip="10.10.1.12", reachable=True, firmware=[]),
        ],
    )

    report = PreflightRunner().run(spec, inventory)

    assert report.ready is False
    assert any(check.status == CheckStatus.FAIL and check.name == "ABC123-bmc" for check in report.checks)
    assert any(check.status == CheckStatus.WARN and check.name == "ABC124-firmware" for check in report.checks)
