from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from strataone.orchestrator import Orchestrator
from strataone.state import SiteSpec, load_site_spec

app = typer.Typer(
    name="strataone",
    help="Vendor-agnostic, hypervisor-agnostic zero-touch infrastructure orchestration.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def validate(site: Path = typer.Argument(..., help="Path to a StrataOne site YAML file.")) -> None:
    """Validate a desired-state site definition."""
    spec = load_site_spec(site)
    console.print(f"[green]valid[/green] {spec.site.name}")
    _print_summary(spec)


@app.command()
def plan(site: Path = typer.Argument(..., help="Path to a StrataOne site YAML file.")) -> None:
    """Generate a dry-run deployment plan."""
    spec = load_site_spec(site)
    plan_result = Orchestrator().plan(spec)

    table = Table(title=f"Deployment plan: {spec.site.name}")
    table.add_column("#", justify="right")
    table.add_column("Phase")
    table.add_column("Action")
    table.add_column("Provider")

    for index, step in enumerate(plan_result.steps, start=1):
        table.add_row(str(index), step.phase, step.action, step.provider)

    console.print(table)


def _print_summary(spec: SiteSpec) -> None:
    table = Table(title="Site summary")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Site", spec.site.name)
    table.add_row("Deployment model", spec.site.deployment_model)
    table.add_row("Hardware provider", spec.hardware.vendor)
    table.add_row("Platform provider", spec.platform.type)
    table.add_row("Nodes", str(len(spec.hardware.nodes)))
    table.add_row("Workloads", ", ".join(spec.workloads.enabled()) or "none")
    console.print(table)
