# StrataOne

StrataOne is a vendor-agnostic, hypervisor-agnostic zero-touch orchestration framework for distributed infrastructure.

It is designed for enterprise edge, branch, ROBO, private cloud, and hybrid cloud environments where hardware vendors, hypervisors, and management planes vary by site.

## Vision

StrataOne turns a desired-state site definition into a repeatable deployment and lifecycle workflow:

```text
Discover -> Prepare hardware -> Provision platform -> Register management plane -> Validate -> Monitor drift -> Remediate
```

The first-class target is Azure Local, but the provider model is intentionally broader:

- Azure Local
- VMware vSphere
- Nutanix AHV
- Proxmox
- Hyper-V
- KVM/libvirt
- OpenShift Virtualization

Hardware support starts with generic Redfish and can be extended with OEM adapters such as Dell iDRAC, HPE iLO, Lenovo XClarity, Supermicro Redfish, or Cisco Intersight.

## Architecture

```text
StrataOne CLI / API
  |
  +-- Desired-state schema
  +-- Orchestrator
  +-- Hardware providers
  |     +-- generic-redfish
  |     +-- dell-idrac
  |     +-- hpe-ilo
  |     +-- lenovo-xclarity
  |
  +-- Platform providers
        +-- azure-local
        +-- vmware-vsphere
        +-- nutanix-ahv
        +-- proxmox
        +-- hyper-v
        +-- kvm
        +-- openshift-virtualization
```

## Quick Start

Install in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Validate the example Azure Local site:

```bash
strataone validate examples/azure-local-branch.yaml
```

Generate a dry-run deployment plan:

```bash
strataone plan examples/azure-local-branch.yaml
```

Run tests:

```bash
pytest
```

## Desired State

Example:

```yaml
site:
  name: branch-001
  location: berlin
  deployment_model: edge-hci

hardware:
  vendor: generic-redfish
  nodes:
    - serial: ABC123
      bmc_ip: 10.10.1.11
      role: host

network:
  management_vlan: 100

platform:
  type: azure-local
  topology: two-node-switchless
  cluster_name: al-branch-001
  azure:
    subscription_id: 00000000-0000-0000-0000-000000000000
    resource_group: rg-branch-001
    region: westeurope
```

## Current Status

This repository currently contains the first buildable foundation:

- Python package and CLI
- Pydantic desired-state schema
- YAML loader
- Dry-run orchestration plan
- Hardware provider contract
- Platform provider contract
- Generic Redfish hardware provider
- Azure Local, vSphere, AHV, Proxmox, and generic platform providers
- Example Azure Local branch configuration
- Unit tests

The next implementation milestone is to add real provider execution with safe dry-run defaults, starting with Redfish inventory discovery and Azure Local ARM/Bicep deployment generation.
