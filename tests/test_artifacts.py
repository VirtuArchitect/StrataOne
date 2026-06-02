from pathlib import Path

from strataone.artifacts import ArtifactGenerator
from strataone.state import load_site_spec


def test_generates_azure_local_artifact_bundle(tmp_path: Path) -> None:
    spec = load_site_spec(Path("examples/azure-local-branch.yaml"))

    bundle = ArtifactGenerator(tmp_path).generate(spec)

    names = {Path(file).name for file in bundle.files}
    assert bundle.site_name == "branch-001"
    assert "manifest.json" in names
    assert "azure-local.parameters.json" in names
    assert "arc-registration.ps1" in names
    assert (tmp_path / "branch-001" / "deployment-plan.json").exists()
