# StrataOne Field Installation Guide

This guide installs StrataOne Infrastructure Orchestrator for an enterprise preview field deployment.

## 1. Prerequisites

- Docker Engine or Docker Desktop with Docker Compose.
- Network access from the API/worker host to target BMC interfaces when live Redfish is enabled.
- DNS/NTP reachability for target deployment sites.
- A dedicated administrator password for the bootstrap `admin` user.
- Optional: HashiCorp Vault or a file-backed vault for BMC/provider secrets.

## 2. Clone And Configure

```powershell
git clone https://github.com/VirtuArchitect/StrataOne.git
cd StrataOne
```

Create or update `.env`:

```text
STRATAONE_AUTH_ENABLED=true
STRATAONE_ADMIN_PASSWORD=ChangeThisPassword!2026
STRATAONE_CORS_ORIGINS=http://localhost:8088,http://127.0.0.1:8088
STRATAONE_STATE_BACKEND=postgres
STRATAONE_POSTGRES_DSN=postgresql://strataone:strataone@postgres:5432/strataone
STRATAONE_EXECUTION_MODE=queued
STRATAONE_QUEUE_BACKEND=redis
STRATAONE_REDIS_URL=redis://redis:6379/0
STRATAONE_REQUIRE_APPROVALS=true
```

For lab-validated live Redfish execution:

```text
STRATAONE_ENABLE_LIVE_REDFISH=true
STRATAONE_REQUIRE_OEM_VALIDATION=true
STRATAONE_OEM_VALIDATION_FILE=.strataone/oem-validation.json
```

## 3. Start The Stack

```powershell
docker compose up -d --build
docker compose ps
```

Expected services:

- `strataone-api` on `http://localhost:8080`
- `strataone-dashboard` on `http://localhost:8088`
- `postgres`
- `redis`
- `strataone-worker`

## 4. First Login

Open `http://localhost:8088` and sign in with:

- Username: `admin`
- Password: the value of `STRATAONE_ADMIN_PASSWORD`

Immediately create named users under Settings > Access & RBAC and avoid shared administrator use.

## 5. Configure Secrets

Go to Settings > Secrets and create credential references for:

- BMC credentials
- Azure Local provider credentials
- Any OEM/provider API credentials

Use the Test action to confirm secret references resolve. The dashboard stores references only; it does not display secret values.

## 6. Configure Providers

Go to Providers:

1. Review built-in hardware providers.
2. Open provider Details.
3. Save provider configuration JSON.
4. Run Test Provider.
5. Record Lab Validation Evidence for live operations.

Live provider execution should remain disabled until the relevant OEM/platform has validation evidence and approval policy is configured.

## 7. Create A Deployment

Go to Deployments or New Deployment:

1. Define site intent.
2. Add hardware nodes.
3. Select platform.
4. Define network and Azure Local settings.
5. Review readiness.
6. Save deployment.
7. Run Validate, Inventory, Preflight, Plan, Artifacts.

## 8. Approvals

Protected actions create approval requests before live execution. Configure policy under Settings > API:

- Action name, such as `deploy-azure-local`
- Required approver roles
- Minimum approvals
- Expiry window

Approvers review Approvals and select Approve, Approve & Run, or Reject.

## 9. Operational Checks

Run:

```powershell
Invoke-RestMethod http://localhost:8080/health
docker compose logs strataone-api --tail 50
docker compose logs strataone-worker --tail 50
```

From the dashboard confirm:

- API status is online.
- Sites, jobs, providers, settings, and approvals load.
- A validation job can run.
- A job report can be exported.

## 10. Upgrade

```powershell
git pull --ff-only
docker compose up -d --build
docker compose ps
```

Schema migrations are tracked in Settings > Database/Migrations.

