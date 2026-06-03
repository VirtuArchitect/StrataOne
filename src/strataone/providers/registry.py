import json
import os
from pathlib import Path

from pydantic import BaseModel

from strataone.state import PlatformType


class ProviderInfo(BaseModel):
    name: str
    type: str
    source: str
    description: str
    vendor_supported: bool = False
    editable: bool = False


def list_providers(plugin_dir: Path | None = None) -> list[ProviderInfo]:
    providers = [
        ProviderInfo(name="generic-redfish", type="hardware", source="built-in", description="Generic Redfish BMC provider", vendor_supported=True),
        ProviderInfo(name="dell-idrac", type="hardware", source="built-in", description="Dell iDRAC provider shim", vendor_supported=True),
        ProviderInfo(name="hpe-ilo", type="hardware", source="built-in", description="HPE iLO provider shim", vendor_supported=True),
        ProviderInfo(name="lenovo-xclarity", type="hardware", source="built-in", description="Lenovo XClarity provider shim", vendor_supported=True),
        ProviderInfo(name="supermicro-redfish", type="hardware", source="built-in", description="Supermicro Redfish provider shim", vendor_supported=True),
        ProviderInfo(name="cisco-intersight", type="hardware", source="built-in", description="Cisco Intersight provider shim", vendor_supported=True),
    ]
    providers.extend(
        ProviderInfo(name=platform.value, type="platform", source="built-in", description=f"{platform.value} platform provider", vendor_supported=True)
        for platform in PlatformType
    )
    providers.extend(_plugin_providers(plugin_dir or Path(os.getenv("STRATAONE_PLUGIN_DIR", "plugins"))))
    return sorted(providers, key=lambda provider: (provider.type, provider.name))


def _plugin_providers(plugin_dir: Path) -> list[ProviderInfo]:
    if not plugin_dir.exists():
        return []
    providers = []
    for manifest in plugin_dir.glob("*/provider.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            providers.append(
                ProviderInfo(
                    name=data["name"],
                    type=data["type"],
                    source=str(manifest.parent),
                    description=data.get("description", "External StrataOne provider"),
                    vendor_supported=bool(data.get("vendor_supported", False)),
                    editable=True,
                )
            )
        except Exception:
            continue
    return providers


def upsert_plugin_provider(provider: ProviderInfo, plugin_dir: Path | None = None) -> ProviderInfo:
    target_root = plugin_dir or Path(os.getenv("STRATAONE_PLUGIN_DIR", "plugins"))
    target = target_root / provider.name
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": provider.name,
        "type": provider.type,
        "description": provider.description,
        "vendor_supported": provider.vendor_supported,
    }
    (target / "provider.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ProviderInfo(
        name=provider.name,
        type=provider.type,
        source=str(target),
        description=provider.description,
        vendor_supported=provider.vendor_supported,
        editable=True,
    )


def delete_plugin_provider(name: str, plugin_dir: Path | None = None) -> bool:
    target_root = plugin_dir or Path(os.getenv("STRATAONE_PLUGIN_DIR", "plugins"))
    target = target_root / name
    manifest = target / "provider.json"
    if not manifest.exists():
        return False
    manifest.unlink()
    try:
        target.rmdir()
    except OSError:
        pass
    return True
