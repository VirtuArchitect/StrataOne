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

Collect read-only hardware inventory through Redfish:

```bash
export STRATAONE_BMC_USERNAME=admin
export STRATAONE_BMC_PASSWORD='change-me'
strataone inventory examples/azure-local-branch.yaml --insecure
```

On Windows PowerShell:

```powershell
$env:STRATAONE_BMC_USERNAME = "admin"
$env:STRATAONE_BMC_PASSWORD = "change-me"
python -m strataone inventory examples\azure-local-branch.yaml --insecure
```

JSON output is available for pipeline integration:

```bash
strataone inventory examples/azure-local-branch.yaml --json
```

Run preflight readiness checks:

```bash
strataone preflight examples/azure-local-branch.yaml --skip-inventory
```

When BMC credentials are present, preflight automatically includes Redfish reachability and inventory checks:

```bash
strataone preflight examples/azure-local-branch.yaml --insecure
```

Generate Azure Local deployment artifacts:

```bash
strataone artifacts examples/azure-local-branch.yaml --output artifacts
```

List built-in and discovered providers:

```bash
strataone providers
```

## Docker

Run the API and dashboard locally:

```bash
docker compose up --build
```

Services:

- Dashboard: http://localhost:8088
- API: http://localhost:8080
- API health: http://localhost:8080/health
- API docs: http://localhost:8080/docs

If either port is unavailable, override it:

```powershell
$env:STRATAONE_DASHBOARD_PORT = "8090"
$env:STRATAONE_API_PORT = "8091"
docker compose up --build
```

Or create a `.env` file from `.env.example`.

The Compose stack currently runs:

- `strataone-api`: FastAPI service for validation, planning, and preflight
- `strataone-dashboard`: static operational dashboard served by Nginx

Runtime state defaults to `.strataone/`:

- `.strataone/strataone.db`
- `.strataone/artifacts/`

Set `STRATAONE_DB`, `STRATAONE_ARTIFACT_DIR`, or `STRATAONE_PLUGIN_DIR` to override those paths.

## API

Start the API directly:

```bash
uvicorn strataone.api:app --reload --port 8080
```

Endpoints:

```text
GET  /health
GET  /providers
GET  /sites/example
GET  /sites
POST /sites
GET  /sites/{site_name}
DELETE /sites/{site_name}
POST /sites/validate
POST /sites/plan
POST /sites/preflight
POST /sites/{site_name}/jobs/{action}
GET  /jobs
GET  /jobs/{job_id}
POST /sites/{site_name}/artifacts
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
- Read-only Redfish inventory collection
- Preflight readiness checks
- FastAPI service
- Docker Compose stack
- Persistent SQLite site registry
- Background job execution
- Azure Local deployment artifact generation
- Redfish capability checks
- Built-in and filesystem provider discovery
- Enterprise dashboard shell
- Hardware provider contract
- Platform provider contract
- Generic Redfish hardware provider
- Azure Local, vSphere, AHV, Proxmox, and generic platform providers
- Example Azure Local branch configuration
- Unit tests

The next implementation milestone is to replace the in-process worker with Redis/NATS-backed distributed execution, add authentication, and implement provider-specific Azure Local execution steps behind explicit approval gates.
