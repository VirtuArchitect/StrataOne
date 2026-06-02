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


def list_providers(plugin_dir: Path | None = None) -> list[ProviderInfo]:
    providers = [
        ProviderInfo(name="generic-redfish", type="hardware", source="built-in", description="Generic Redfish BMC provider"),
        ProviderInfo(name="dell-idrac", type="hardware", source="built-in", description="Dell iDRAC provider shim"),
        ProviderInfo(name="hpe-ilo", type="hardware", source="built-in", description="HPE iLO provider shim"),
        ProviderInfo(name="lenovo-xclarity", type="hardware", source="built-in", description="Lenovo XClarity provider shim"),
        ProviderInfo(name="supermicro-redfish", type="hardware", source="built-in", description="Supermicro Redfish provider shim"),
        ProviderInfo(name="cisco-intersight", type="hardware", source="built-in", description="Cisco Intersight provider shim"),
    ]
    providers.extend(
        ProviderInfo(name=platform.value, type="platform", source="built-in", description=f"{platform.value} platform provider")
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
                )
            )
        except Exception:
            continue
    return providers
