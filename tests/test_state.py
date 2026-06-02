from pathlib import Path

import pytest
from pydantic import ValidationError

from strataone.state import SiteSpec, load_site_spec


def test_loads_example_site_spec() -> None:
    spec = load_site_spec(Path("examples/azure-local-branch.yaml"))

    assert spec.site.name == "branch-001"
    assert spec.platform.type == "azure-local"
    assert spec.workloads.enabled() == ["aks", "arc_vms"]


def test_azure_local_requires_azure_deployment_fields() -> None:
    payload = {
        "site": {"name": "branch-002", "location": "london"},
        "hardware": {
            "vendor": "generic-redfish",
            "nodes": [{"serial": "ABC125", "bmc_ip": "10.10.1.13"}],
        },
        "network": {"management_vlan": 100},
        "platform": {"type": "azure-local"},
    }

    with pytest.raises(ValidationError, match="platform.azure.subscription_id"):
        SiteSpec.model_validate(payload)
