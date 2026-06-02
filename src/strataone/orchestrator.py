from strataone.plan import DeploymentPlan, PlanStep
from strataone.providers.hardware import get_hardware_provider
from strataone.providers.platform import get_platform_provider
from strataone.state import SiteSpec


class Orchestrator:
    """Coordinates desired-state validation and provider-specific execution."""

    def plan(self, spec: SiteSpec) -> DeploymentPlan:
        hardware = get_hardware_provider(spec.hardware.vendor)
        platform = get_platform_provider(spec.platform.type)

        steps = [
            PlanStep(phase="validate", action="Validate desired-state schema", provider="strataone"),
            *hardware.plan(spec),
            *platform.plan(spec),
            PlanStep(phase="validate", action="Run post-deployment health checks", provider="strataone"),
            PlanStep(phase="lifecycle", action="Record baseline inventory and compliance state", provider="strataone"),
        ]
        return DeploymentPlan(site_name=spec.site.name, steps=steps)
