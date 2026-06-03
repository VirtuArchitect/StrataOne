from enum import StrEnum
import ipaddress
from pathlib import Path
import re
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class PlatformType(StrEnum):
    AZURE_LOCAL = "azure-local"
    VMWARE_VSPHERE = "vmware-vsphere"
    NUTANIX_AHV = "nutanix-ahv"
    PROXMOX = "proxmox"
    HYPER_V = "hyper-v"
    KVM = "kvm"
    OPENSHIFT_VIRT = "openshift-virtualization"


class NodeSpec(BaseModel):
    serial: str
    bmc_ip: str
    role: str = "host"

    @field_validator("serial")
    @classmethod
    def validate_serial(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value):
            raise ValueError("serial must be 1-64 characters and contain only letters, numbers, dot, underscore, colon, or dash")
        return value

    @field_validator("bmc_ip")
    @classmethod
    def validate_bmc_ip(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("bmc_ip must be a valid IPv4 or IPv6 address") from exc
        return value


class SiteIdentity(BaseModel):
    name: str
    location: str
    deployment_model: str = "edge-hci"


class HardwareSpec(BaseModel):
    vendor: str = Field(examples=["generic-redfish", "dell-idrac", "hpe-ilo"])
    nodes: list[NodeSpec]

    @field_validator("nodes")
    @classmethod
    def require_nodes(cls, value: list[NodeSpec]) -> list[NodeSpec]:
        if not value:
            raise ValueError("at least one hardware node is required")
        return value


class NetworkSpec(BaseModel):
    management_vlan: int
    storage_vlan: int | None = None
    vm_vlan: int | None = None
    dns_servers: list[str] = Field(default_factory=list)
    ntp_servers: list[str] = Field(default_factory=list)


class AzureSpec(BaseModel):
    subscription_id: str | None = None
    tenant_id: str | None = None
    resource_group: str | None = None
    region: str | None = None


class PlatformSpec(BaseModel):
    type: PlatformType
    topology: str | None = None
    management_endpoint: str | None = None
    cluster_name: str | None = None
    azure: AzureSpec | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class WorkloadSpec(BaseModel):
    aks: bool = False
    avd: bool = False
    arc_vms: bool = False
    kubernetes: bool = False

    def enabled(self) -> list[str]:
        return [name for name, enabled in self.model_dump().items() if enabled]


class SiteSpec(BaseModel):
    site: SiteIdentity
    hardware: HardwareSpec
    network: NetworkSpec
    platform: PlatformSpec
    workloads: WorkloadSpec = Field(default_factory=WorkloadSpec)

    @field_validator("platform")
    @classmethod
    def require_azure_fields_for_azure_local(cls, value: PlatformSpec) -> PlatformSpec:
        if value.type != PlatformType.AZURE_LOCAL:
            return value

        missing = []
        azure = value.azure
        for field_name in ("subscription_id", "resource_group", "region"):
            if azure is None or getattr(azure, field_name) in (None, ""):
                missing.append(f"platform.azure.{field_name}")

        if missing:
            raise ValueError(f"Azure Local platform requires: {', '.join(missing)}")
        return value


def load_site_spec(path: Path) -> SiteSpec:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return SiteSpec.model_validate(raw)
    except FileNotFoundError:
        raise
    except ValidationError:
        raise
    except Exception as exc:
        raise ValueError(f"failed to load site spec {path}: {exc}") from exc
