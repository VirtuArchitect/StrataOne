# StrataOne

StrataOne is a vendor-agnostic, hypervisor-agnostic zero-touch orchestration framework for distributed infrastructure.

It is designed for enterprise edge, branch, ROBO, private cloud, and hybrid cloud environments where hardware vendors, hypervisors, and management planes vary by site.

See [CHANGELOG.md](CHANGELOG.md) for release notes and feature history.

Field and operator documentation:

- [Field Installation Guide](docs/FIELD_INSTALLATION_GUIDE.md)
- [User Guide](docs/USER_GUIDE.md)

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
- Reverse proxy / single front door: http://localhost:8089
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

- `strataone-api`: FastAPI service for validation, planning, and orchestration requests
- `strataone-worker`: queue worker for Redis-dispatched orchestration jobs
- `strataone-dashboard`: static operational dashboard served by Nginx
- `strataone-proxy`: Nginx reverse proxy for dashboard and API routing
- `postgres`: durable state backend for sites, jobs, inventory, users, and roles
- `redis`: production job dispatch queue

Runtime state uses PostgreSQL and Redis in Compose. Local development can still use SQLite by setting `STRATAONE_STATE_BACKEND=sqlite`:

- `.strataone/strataone.db`
- `.strataone/artifacts/`

Set `STRATAONE_POSTGRES_DSN`, `STRATAONE_REDIS_URL`, `STRATAONE_DB`, `STRATAONE_ARTIFACT_DIR`, or `STRATAONE_PLUGIN_DIR` to override runtime paths and backends.
Set `STRATAONE_CORS_ORIGINS` to the trusted dashboard/API origins allowed to call the API. Set `STRATAONE_SEED_EXAMPLE=false` for production-like environments so the example site is not inserted automatically.
API responses include production security headers by default, including CSP, frame protection, content-type sniffing protection, and referrer policy. Enable HSTS only when StrataOne is served over HTTPS:

```env
STRATAONE_RATE_LIMIT_ENABLED=true
STRATAONE_RATE_LIMIT_REQUESTS=120
STRATAONE_RATE_LIMIT_WINDOW_SECONDS=60
STRATAONE_HSTS_ENABLED=true
```

Protected API routes enforce bearer-token authentication by default. Set `STRATAONE_AUTH_ENABLED=false` only for isolated local development. Use a bootstrap token for initial administration, or provide named API tokens mapped to RBAC roles:

```env
STRATAONE_AUTH_ENABLED=true
STRATAONE_BOOTSTRAP_TOKEN=change-this-token
STRATAONE_ADMIN_PASSWORD=change-this-password
STRATAONE_API_TOKENS=operator-token=edge.operator:Viewer,Operator
```

API tokens can optionally scope access to a tenant with `@tenant-id`. Tenant enforcement filters sites, jobs, and inventory by tenant:

```env
STRATAONE_TENANT_ENFORCEMENT=true
STRATAONE_API_TOKENS=tenant-a-token=edge.operator:Viewer,Operator@tenant-a
```

The dashboard signs in with local username/password sessions. Session tokens are kept in browser session storage rather than persistent local storage. The default Compose account is `admin` with `change-this-password`; override `STRATAONE_ADMIN_PASSWORD` before production use. Bootstrap/API tokens are still available for automation and emergency administration. When `STRATAONE_ENVIRONMENT=production`, startup is blocked if placeholder bootstrap, admin, or PostgreSQL passwords are still configured.

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
GET  /providers/{provider_name}
POST /providers/{provider_name}/config
POST /providers/{provider_name}/validation/run
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
GET  /jobs/{job_id}/events
GET  /jobs/{job_id}/events/stream
POST /jobs/worker/run-once
GET  /audit
GET  /approvals
POST /approvals/{approval_id}/approve
GET  /validation/oem
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
deploy-azure-local
drift-detect
node-replacement
```

### Deployment Execution Model

Current deployment is approval-oriented and staged:

1. Generate desired state for a site.
2. Run inventory and preflight checks.
3. Generate deployment artifacts.
4. Optionally run `mount-iso` to prepare Redfish virtual media boot.
5. Hand off to provider-specific execution gates.

The `mount-iso` job defaults to a simulated execution contract. Set `STRATAONE_ENABLE_LIVE_REDFISH=true` to execute Redfish `VirtualMedia.InsertMedia` and one-time CD/DVD boot override calls against discovered BMC endpoints.

Live or materially changing actions are approval-gated when `STRATAONE_REQUIRE_APPROVALS=true`. A request returns an `approval_id`; approve it through `POST /approvals/{approval_id}/approve`, then retry the action with that `approval_id`.

Production job execution uses PostgreSQL for durable state and Redis for dispatch:

```env
STRATAONE_STATE_BACKEND=postgres
STRATAONE_POSTGRES_DSN=postgresql://strataone:strataone@postgres:5432/strataone
STRATAONE_EXECUTION_MODE=queued
STRATAONE_QUEUE_BACKEND=redis
STRATAONE_REDIS_URL=redis://redis:6379/0
```

Run a worker directly with:

```bash
strataone worker
```

Set `STRATAONE_REQUIRE_OEM_VALIDATION=true` to require OEM lab validation evidence before live Redfish operations are allowed. Validation records are read from `STRATAONE_OEM_VALIDATION_FILE`:

```json
{
  "records": [
    {
      "provider": "dell-idrac",
      "operation": "redfish-virtual-media",
      "status": "validated",
      "lab": "edge-lab-1",
      "validated_at": "2026-06-03T12:00:00Z",
      "evidence": "change-12345"
    }
  ]
}
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
- Docker Compose stack with API, dashboard, worker, PostgreSQL, and Redis
- PostgreSQL-capable persistent state backend with SQLite local fallback
- Redis-backed queue dispatch with CLI/API worker execution
- Durable queued job parameters
- Schema migration registry
- Audit log, approvals, server-side session revoke, and job event streaming
- Bearer-token authentication and RBAC route enforcement
- Environment, file, and HashiCorp Vault-compatible BMC secret providers
- Dashboard-driven Redfish inventory jobs
- Stored inventory-backed preflight checks
- Azure Local deployment artifact generation
- Redfish capability checks
- Redfish virtual-media insert/eject and boot override client operations
- Azure Local staged deployment execution contract
- Drift detection and node replacement lifecycle workflows
- Provider detail and configuration API/dashboard controls
- Built-in and filesystem provider discovery
- Enterprise dashboard shell
- Hardware provider contract
- Platform provider contract
- Generic Redfish hardware provider
- Azure Local, vSphere, AHV, Proxmox, and generic platform providers
- OEM validation registry for live Redfish/provider execution gates
- Example Azure Local branch configuration
- Unit and integration-style Redfish mock tests

The next implementation milestone is to implement provider-specific Azure Local execution steps behind explicit approval gates and validate each OEM provider in a hardware lab.

## Production Readiness Notes

StrataOne now includes the core controls expected before lab production validation:

- Authentication and enforced RBAC are available through bearer tokens and route permissions.
- CORS is configurable by environment and wildcard origins are rejected when auth is enabled.
- BMC credentials can be resolved from env, local secret files, or a Vault-compatible API.
- Redfish virtual media and boot override calls have mock integration coverage.
- PostgreSQL and Redis are available as the production state and queue backend.
- Live Redfish operations can be blocked unless OEM lab validation evidence is registered.

Remaining enterprise hardening items:

- SQLite is still best suited to local/dev and small lab installs.
- Live Redfish execution still requires real OEM hardware validation before broad rollout.
- Provider implementations beyond Azure Local planning are currently scaffolds unless explicitly implemented and validated.
