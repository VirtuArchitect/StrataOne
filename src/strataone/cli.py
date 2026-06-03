import json
import os
from pathlib import Path
import time

import typer
from rich.console import Console
from rich.table import Table

from strataone.artifacts import ArtifactGenerator
from strataone.inventory import InventoryReport
from strataone.jobs import JobRunner
from strataone.orchestrator import Orchestrator
from strataone.preflight import CheckStatus, PreflightReport, PreflightRunner
from strataone.providers.registry import list_providers
from strataone.providers.hardware import get_hardware_provider
from strataone.redfish import RedfishCredentials
from strataone.state import SiteSpec, load_site_spec
from strataone.store import StrataStore

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


@app.command()
def inventory(
    site: Path = typer.Argument(..., help="Path to a StrataOne site YAML file."),
    username_env: str = typer.Option(
        "STRATAONE_BMC_USERNAME",
        help="Environment variable containing the BMC username.",
    ),
    password_env: str = typer.Option(
        "STRATAONE_BMC_PASSWORD",
        help="Environment variable containing the BMC password.",
    ),
    timeout: float = typer.Option(10, help="Per-request timeout in seconds."),
    insecure: bool = typer.Option(False, help="Disable TLS certificate verification for BMC HTTPS endpoints."),
    output_json: bool = typer.Option(False, "--json", help="Print inventory as JSON."),
) -> None:
    """Collect read-only hardware inventory through the configured hardware provider."""
    spec = load_site_spec(site)
    credentials = _load_bmc_credentials(username_env, password_env)
    provider = get_hardware_provider(spec.hardware.vendor)
    report = provider.inventory(spec, credentials, timeout=timeout, verify_tls=not insecure)

    if output_json:
        typer.echo(json.dumps(report.model_dump(), indent=2))
        return

    _print_inventory(report)


@app.command()
def preflight(
    site: Path = typer.Argument(..., help="Path to a StrataOne site YAML file."),
    username_env: str = typer.Option(
        "STRATAONE_BMC_USERNAME",
        help="Environment variable containing the BMC username.",
    ),
    password_env: str = typer.Option(
        "STRATAONE_BMC_PASSWORD",
        help="Environment variable containing the BMC password.",
    ),
    timeout: float = typer.Option(10, help="Per-request timeout in seconds."),
    insecure: bool = typer.Option(False, help="Disable TLS certificate verification for BMC HTTPS endpoints."),
    skip_inventory: bool = typer.Option(False, help="Run desired-state checks without contacting BMC endpoints."),
    output_json: bool = typer.Option(False, "--json", help="Print preflight report as JSON."),
) -> None:
    """Run deployment readiness checks for a site."""
    spec = load_site_spec(site)
    report = PreflightRunner().run(spec, _collect_inventory_if_available(spec, username_env, password_env, timeout, not insecure, skip_inventory))

    if output_json:
        typer.echo(json.dumps(report.model_dump(), indent=2))
        raise typer.Exit(0 if report.ready else 1)

    _print_preflight(report)
    raise typer.Exit(0 if report.ready else 1)


@app.command()
def artifacts(
    site: Path = typer.Argument(..., help="Path to a StrataOne site YAML file."),
    output: Path = typer.Option(Path("artifacts"), help="Artifact output directory."),
    output_json: bool = typer.Option(False, "--json", help="Print artifact bundle as JSON."),
) -> None:
    """Generate deployment artifacts for a site."""
    spec = load_site_spec(site)
    bundle = ArtifactGenerator(output).generate(spec)
    if output_json:
        typer.echo(json.dumps(bundle.model_dump(), indent=2))
        return
    table = Table(title=f"Artifacts: {bundle.site_name}")
    table.add_column("File")
    for file in bundle.files:
        table.add_row(file)
    console.print(table)


@app.command()
def providers(output_json: bool = typer.Option(False, "--json", help="Print providers as JSON.")) -> None:
    """List built-in and filesystem-discovered providers."""
    provider_list = list_providers()
    if output_json:
        typer.echo(json.dumps([provider.model_dump() for provider in provider_list], indent=2))
        return
    table = Table(title="Providers")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Source")
    table.add_column("Description")
    for provider in provider_list:
        table.add_row(provider.type, provider.name, provider.source, provider.description)
    console.print(table)


@app.command()
def worker(
    once: bool = typer.Option(False, "--once", help="Run a single queued job and exit."),
    idle_sleep: float = typer.Option(2.0, help="Seconds to sleep when no job is available."),
) -> None:
    """Run queued orchestration jobs from the configured queue backend."""
    runner = JobRunner(StrataStore())
    while True:
        job_id = runner.run_queued_once()
        if job_id:
            console.print(f"[green]completed queued job[/green] {job_id}")
        elif once:
            console.print("[yellow]no queued job available[/yellow]")
            return
        else:
            time.sleep(idle_sleep)
        if once:
            return


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


def _collect_inventory_if_available(
    spec: SiteSpec,
    username_env: str,
    password_env: str,
    timeout: float,
    verify_tls: bool,
    skip_inventory: bool,
) -> InventoryReport | None:
    if skip_inventory:
        return None

    username = os.getenv(username_env)
    password = os.getenv(password_env)
    if not username or not password:
        return None

    provider = get_hardware_provider(spec.hardware.vendor)
    return provider.inventory(
        spec,
        RedfishCredentials(username=username, password=password),
        timeout=timeout,
        verify_tls=verify_tls,
    )


def _load_bmc_credentials(username_env: str, password_env: str) -> RedfishCredentials:
    username = os.getenv(username_env)
    password = os.getenv(password_env)
    missing = [name for name, value in ((username_env, username), (password_env, password)) if not value]
    if missing:
        console.print(f"[red]missing credentials[/red] set {', '.join(missing)}")
        raise typer.Exit(2)
    return RedfishCredentials(username=username, password=password)


def _print_inventory(report: InventoryReport) -> None:
    table = Table(title=f"Hardware inventory: {report.site_name}")
    table.add_column("Serial")
    table.add_column("BMC")
    table.add_column("Reachable")
    table.add_column("Model")
    table.add_column("BIOS")
    table.add_column("CPU")
    table.add_column("Memory")
    table.add_column("NICs")
    table.add_column("Storage")
    table.add_column("Error")

    for node in report.nodes:
        table.add_row(
            node.serial,
            node.bmc_ip,
            "yes" if node.reachable else "no",
            " ".join(value for value in (node.manufacturer, node.model) if value) or "-",
            node.bios_version or "-",
            str(node.processor_count) if node.processor_count is not None else "-",
            f"{node.memory_gib} GiB" if node.memory_gib is not None else "-",
            str(len(node.nics)),
            str(len(node.storage)),
            node.error or "-",
        )

    console.print(table)
    console.print(f"{report.reachable_count}/{len(report.nodes)} nodes reachable via {report.provider}")


def _print_preflight(report: PreflightReport) -> None:
    table = Table(title=f"Preflight: {report.site_name}")
    table.add_column("Status")
    table.add_column("Category")
    table.add_column("Check")
    table.add_column("Message")

    for check in report.checks:
        style = {
            CheckStatus.PASS: "green",
            CheckStatus.WARN: "yellow",
            CheckStatus.FAIL: "red",
        }[check.status]
        table.add_row(f"[{style}]{check.status.value}[/{style}]", check.category, check.name, check.message)

    console.print(table)
    outcome = "[green]READY[/green]" if report.ready else "[red]NOT READY[/red]"
    console.print(f"{outcome}: {report.pass_count} pass, {report.warn_count} warn, {report.fail_count} fail")
