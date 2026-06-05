# Security Policy

## Supported Versions

StrataOne is currently an enterprise preview project. Security fixes are applied to the active `main` branch and the latest preview release line.

| Version | Status |
| --- | --- |
| 0.3.x | Supported preview |
| < 0.3.0 | Not supported |

## Reporting Security Issues

Please do not open public GitHub issues for suspected vulnerabilities that include sensitive details, exploit paths, credentials, infrastructure names, or customer data.

Report security concerns privately to the repository owner or project maintainer. Include:

- A concise description of the issue.
- Affected component, endpoint, file, or workflow.
- Steps to reproduce in a local or lab environment.
- Expected and observed behavior.
- Any relevant logs or screenshots with secrets redacted.

## Security Baseline

The project includes a baseline defensive security assessment covering authentication, RBAC, tenant isolation, path traversal, SSRF-style outbound requests, dependency auditing, static analysis, and CI security gates.

See [docs/SECURITY_ASSESSMENT.md](docs/SECURITY_ASSESSMENT.md) for the latest published assessment summary.

## Production Caveat

This repository-level assessment is not a substitute for a formal third-party penetration test, live provider validation, or environment-specific cloud security review. Production deployments should validate:

- TLS termination and HSTS posture.
- Network exposure and firewall policy.
- Identity provider integration.
- Vault and secret rotation.
- Tenant isolation requirements.
- Provider/OEM live execution safety.
- Backup, recovery, logging, and monitoring.

