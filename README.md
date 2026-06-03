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
Set `STRATAONE_CORS_ORIGINS` to the trusted dashboard/API origins allowed to call the API. Set `STRATAONE_SEED_EXAMPLE=false` for production-like environments so the example site is not inserted automatically.

Protected API routes enforce bearer-token authentication when `STRATAONE_AUTH_ENABLED=true`. Use a bootstrap token for initial administration, or provide named API tokens mapped to RBAC roles:

```env
STRATAONE_AUTH_ENABLED=true
STRATAONE_BOOTSTRAP_TOKEN=change-this-token
STRATAONE_API_TOKENS=operator-token=edge.operator:Viewer,Operator
```

Dashboard inventory jobs can use transient BMC credentials entered in the UI, but production deployments should resolve credentials through a secret provider. Supported providers are environment variables, a local JSON secret file, or a HashiCorp Vault-compatible endpoint:

```env
STRATAONE_VAULT_PROVIDER=env
STRATAONE_BMC_USERNAME=admin
STRATAONE_BMC_PASSWORD=change-me
STRATAONE_BMC_INSECURE=true
STRATAONE_BMC_TIMEOUT=10
```

For file-backed secrets, set `STRATAONE_VAULT_PROVIDER=file` and `STRATAONE_VAULT_FILE=.strataone/secrets.json` with this shape:

```json
{
  "default": { "username": "admin", "password": "change-me" },
  "sites": {
    "branch-001": { "username": "site-admin", "password": "site-secret" }
  }
}
```

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
POST /jobs/worker/run-once
GET  /sites/{site_name}/inventory
POST /sites/{site_name}/inventory
POST /sites/{site_name}/artifacts
```

Supported job actions:

```text
validate
plan
inventory
preflight
artifacts
mount-iso
```

### Deployment Execution Model

Current deployment is approval-oriented and staged:

1. Generate desired state for a site.
2. Run inventory and preflight checks.
3. Generate deployment artifacts.
4. Optionally run `mount-iso` to prepare Redfish virtual media boot.
5. Hand off to provider-specific execution gates.

The `mount-iso` job defaults to a simulated execution contract. Set `STRATAONE_ENABLE_LIVE_REDFISH=true` to execute Redfish `VirtualMedia.InsertMedia` and one-time CD/DVD boot override calls against discovered BMC endpoints.

Job execution defaults to inline background workers. Set `STRATAONE_EXECUTION_MODE=queued` when an external worker should claim durable SQLite jobs through `POST /jobs/worker/run-once`. The schema now persists job parameters so this can evolve cleanly toward PostgreSQL plus Redis, NATS, Celery, or another enterprise queue.

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
- Durable queued job parameters and worker claim endpoint
- Bearer-token authentication and RBAC route enforcement
- Environment, file, and HashiCorp Vault-compatible BMC secret providers
- Dashboard-driven Redfish inventory jobs
- Stored inventory-backed preflight checks
- Azure Local deployment artifact generation
- Redfish capability checks
- Redfish virtual-media insert/eject and boot override client operations
- Built-in and filesystem provider discovery
- Enterprise dashboard shell
- Hardware provider contract
- Platform provider contract
- Generic Redfish hardware provider
- Azure Local, vSphere, AHV, Proxmox, and generic platform providers
- Example Azure Local branch configuration
- Unit and integration-style Redfish mock tests

The next implementation milestone is to replace the SQLite worker claim path with a production queue backend and implement provider-specific Azure Local execution steps behind explicit approval gates.

## Production Readiness Notes

StrataOne now includes the core controls expected before lab production validation:

- Authentication and enforced RBAC are available through bearer tokens and route permissions.
- CORS is configurable by environment and wildcard origins are rejected when auth is enabled.
- BMC credentials can be resolved from env, local secret files, or a Vault-compatible API.
- Redfish virtual media and boot override calls have mock integration coverage.

Remaining enterprise hardening items:

- SQLite is still best suited to local/dev and small lab installs; multi-operator production should move to PostgreSQL plus Redis/NATS or an equivalent queue.
- Live Redfish execution should be validated per OEM in a hardware lab before broad rollout.
- Provider implementations beyond Azure Local planning are currently scaffolds unless explicitly implemented and validated.
