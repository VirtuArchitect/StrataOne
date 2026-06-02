import json

from strataone.providers.registry import list_providers


def test_lists_builtin_and_filesystem_providers(tmp_path) -> None:
    plugin = tmp_path / "example"
    plugin.mkdir()
    (plugin / "provider.json").write_text(
        json.dumps({"name": "example-provider", "type": "hardware", "description": "Example plugin"}),
        encoding="utf-8",
    )

    providers = list_providers(tmp_path)
    names = {provider.name for provider in providers}

    assert "generic-redfish" in names
    assert "azure-local" in names
    assert "example-provider" in names
