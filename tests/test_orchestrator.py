from pathlib import Path

from strataone.orchestrator import Orchestrator
from strataone.state import load_site_spec


def test_plan_includes_hardware_platform_and_workload_steps() -> None:
    spec = load_site_spec(Path("examples/azure-local-branch.yaml"))

    plan = Orchestrator().plan(spec)
    actions = [step.action for step in plan.steps]

    assert plan.site_name == "branch-001"
    assert "Discover nodes through Redfish" in actions
    assert "Deploy Azure Local instance through ARM/Bicep desired state" in actions
    assert "Deploy AKS enabled by Azure Arc" in actions
    assert "Enable Arc VM management" in actions
