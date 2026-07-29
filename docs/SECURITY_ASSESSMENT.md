# Security Assessment Summary

Assessment date: 2026-07-29

Project version: StrataOne 0.4.0

Assessment type: Local defensive repository assessment and targeted API security validation.

## Scope

The assessment covered the StrataOne repository, dashboard, API, persistence layer, Docker/Compose configuration, CI workflow, and local test suite.

Areas reviewed:

- Authentication and session handling.
- RBAC and tenant isolation.
- Job, approval, artifact, and inventory access control.
- Path traversal and filesystem containment.
- SSRF-style outbound URL behavior.
- Secret handling and audit redaction.
- Dependency and static security scanning.
- Docker Compose and CI security posture.

## Tools And Checks

Commands executed during validation:

```powershell
python -m pytest -q
python -m pip_audit --skip-editable
python -m bandit -r src --severity-level medium
docker compose config --quiet
git diff --check
```

Latest local results:

- Unit and regression tests: `78 passed`
- Dependency audit: no known vulnerabilities found
- Static security scan: no medium-or-high-severity Bandit findings
- Docker Compose configuration: valid
- Git diff whitespace check: clean

## Findings Addressed

The assessment identified and remediated the following security issues:

| Area | Risk | Remediation |
| --- | --- | --- |
| Tenant isolation | Cross-tenant job detail and event access was possible when a job ID was known. | Job, event, report, control, approval, artifact, and inventory paths now enforce tenant scope. |
| Path traversal | Site names could be used as filesystem path components for artifact generation. | Site names now use strict validation and artifact paths are checked to remain under the artifact root. |
| Authentication default | Direct API startup could default to unauthenticated local-dev behavior. | Authentication now defaults to enabled unless explicitly disabled for local development. |
| SSRF | ISO validation and notification webhook tests could call arbitrary local/private targets. | Outbound URL validation now blocks localhost, private, reserved, link-local, multicast, and unresolved targets. |
| Token handling | Dashboard sessions used persistent local storage and WebSocket query tokens. | Dashboard tokens now use session storage, and authenticated live event streaming avoids bearer tokens in URLs. |
| Audit secrecy | Provider configuration audit events could include sensitive values. | Provider configuration audit payloads now redact sensitive key names. |
| Discovery tenancy | Discovery runs were globally visible and import wrote sites outside the requester tenant scope. | Discovery runs are tenant-owned and scoped for list, execute, delete, and import; imported sites inherit requester tenant scope. |
| Durable secret exposure | Transient job credentials could be persisted in job params, approval details, and operational event data. | Durable job params, approvals, audit details, job events, and discovery results are redacted before storage; inline execution keeps one-time params in memory only. |
| Dependency hygiene | Dev dependency declaration used `httpx2`; local audit flagged vulnerable pytest. | Dev dependencies now use `httpx`, pytest is pinned to a fixed major line, and audit tools are included. |
| Dependency repeatability | CI and container builds resolved dependencies without a shared constraints file. | CI and Docker installs now use `requirements-constraints.txt` with audited minimum versions. |
| CI visibility | CI did not run dependency or static security gates. | CI now runs tests, `pip-audit`, Bandit medium-or-higher severity scanning, Docker build, and Compose validation. |

## Current Security Controls

Implemented controls include:

- Bearer-token and local password session authentication.
- RBAC route enforcement.
- Server-side session revocation.
- Tenant-scoped site, job, inventory, approval, discovery, and artifact access.
- Configurable CORS with wildcard rejection when auth is enabled.
- Security headers and CSP through API/proxy/dashboard configuration.
- Rate limiting middleware.
- Approval gates for protected live-impact actions.
- Secret reference model with environment, file, and Vault-compatible providers.
- Production startup guard for known placeholder credentials.
- Production startup guard for auth, tenant enforcement, PostgreSQL state, and Redis queue posture.
- Dependency audit and static security gates in CI.
- Durable redaction for sensitive job, approval, audit, event, and discovery payloads.

## Limitations

This assessment was performed locally against repository code and local API behavior. It does not claim to be:

- A formal third-party penetration test.
- A live cloud/provider/OEM validation.
- A full red-team engagement.
- A compliance certification.
- A guarantee of production security in every deployment environment.

Before production use, StrataOne should still undergo environment-specific validation, including TLS, identity provider integration, network segmentation, Vault integration, backup and recovery, live Redfish/OEM execution, Azure Local provider actions, monitoring, and incident response procedures.

## Recommended Ongoing Security Work

- Add third-party penetration testing before production customer deployment.
- Add live lab validation evidence for each hardware and hypervisor provider.
- Add SAST/DAST reporting artifacts to CI.
- Generate SBOMs and signed release attestations.
- Add container image vulnerability scanning.
- Add OIDC/SAML enterprise identity provider integration.
- Add centralized audit export to SIEM or log analytics.
