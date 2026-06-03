# StrataOne User Guide

StrataOne is a vendor-agnostic and hypervisor-agnostic infrastructure orchestration console for zero-touch style deployment workflows.

## Dashboard

The Dashboard shows fleet readiness, job counts, successful runs, and attention items. KPI cards are clickable when data exists.

Use the main navigation for:

- Deployments: create and manage desired state.
- Sites: select registered sites and run actions.
- Providers: configure hardware and platform integrations.
- Artifacts: browse generated deployment files.
- Orchestration Runs: inspect jobs, logs, reports, retry, resume, or cancel.
- Approvals: approve or reject protected live actions.
- Lifecycle: run drift detection and node replacement workflows.
- Settings: manage RBAC, secrets, database, providers, API policy, artifacts, and audit.
- About: version, ownership, release notes, and product scope.

## Deployments

Create a deployment by selecting New Deployment.

1. Enter site name, location, deployment model, and cluster name.
2. Select hardware provider.
3. Add nodes with serial, BMC IP, and role.
4. Select platform provider.
5. Enter network VLAN, DNS, NTP, and Azure Local values.
6. Review readiness.
7. Save Deployment or Save & Plan.

Additional nodes can be added from the node editor. Invalid IP addresses, duplicate serials, and missing Azure Local settings are flagged by validation.

## Sites

Sites represent persistent desired state. Select a site to:

- Validate desired state.
- Generate a plan.
- Run inventory.
- Run preflight.
- Generate artifacts.
- Mount or eject ISO media.
- Edit or delete the site.

## Providers

Providers abstract hardware vendors and virtualization/cloud platforms.

Provider detail pages show:

- Type, source, support posture, and configuration status.
- Configuration JSON.
- Provider test action.
- Lab validation evidence.

Record validation evidence before enabling live Redfish or provider execution.

## Discovery

Use discovery to plan BMC candidate addresses from a CIDR range. Discovery can be executed in simulated or live modes depending on configuration.

After a discovery run:

- Inspect candidate results.
- Import candidates into a managed site.
- Delete old discovery runs.

## ISO Registry

Register deployment ISO URIs under the ISO registry. Each ISO can be validated for reachability.

Use Mount ISO from the selected site panel to stage virtual media. Protected ISO operations may require approval.

## Orchestration Runs

Each job has:

- Status, site, action, start/finish time, and event count.
- Stage timeline.
- Event stream.
- Inspect Result.
- Export Report.
- Rerun.
- Resume for failed/canceled jobs.
- Cancel for queued/running jobs.

Reports include job metadata, site state, events, and status summary.

## Approvals

Protected actions appear in Approvals.

Approval records show:

- Requested action and site.
- Reason/policy.
- Required approvals.
- Votes already recorded.
- Expiry time.

Approvers can vote, approve and run, or reject. If a policy requires multiple approvals, the run remains pending until enough votes are recorded.

## Lifecycle

Lifecycle workflows include:

- Firmware compliance readiness.
- Drift detection.
- Update rings.
- Node replacement.

Drift detection compares desired nodes against latest inventory and highlights missing, unexpected, or unreachable nodes. Node replacement creates a guided stage plan for replacing failed hardware.

## Settings

Access & RBAC:

- Create roles.
- Pick permissions.
- Create users.
- Set user password.
- Disable users.
- Revoke active sessions.

Secrets:

- Create references to external secrets.
- Test references.

API:

- Configure approval policy rules.
- Review CORS, health, docs, and session posture.

Audit:

- Review security, configuration, provider, job, and approval activity.

## Recommended Operating Sequence

1. Create deployment.
2. Run validation.
3. Run inventory.
4. Run preflight.
5. Generate artifacts.
6. Register and validate ISO if needed.
7. Request/approve protected live action.
8. Run deployment or lifecycle workflow.
9. Export job report.

