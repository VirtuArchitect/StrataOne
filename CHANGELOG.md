# Changelog

All notable changes to StrataOne are documented in this file.

The format follows the spirit of Keep a Changelog, and this project currently uses preview-versioned releases.

## [Unreleased]

## [0.2.0-preview] - 2026-06-04

### Added

- API rate limiting middleware with configurable request/window limits.
- API security headers for CSP, frame protection, content sniffing protection, referrer policy, permissions policy, and optional HSTS.
- Nginx dashboard security headers and static asset cache policy.
- Nginx reverse proxy/front door for combined dashboard and API routing.
- GitHub Actions CI workflow for tests, Docker image build, and Compose validation.
- Tenant-aware access metadata and tenant-scoped filtering for sites, jobs, and inventory.
- Provider validation harness endpoint with live-provider gating.
- Enterprise-control regression tests covering rate limits, headers, tenant scoping, provider validation, CI, and proxy config.
- Dashboard approval request form for protected live actions.
- Clickable dashboard KPI tiles for sites, all jobs, successful jobs, and attention jobs.
- Sidebar navigation icons for primary dashboard sections.
- Secret reference registry and BMC discovery planner.
- Provider detail configuration templates for faster provider onboarding.
- Credential references in jobs, executable discovery plans, ISO registry, ISO eject, and job cancel/retry controls.
- Vendor mark badges beside provider names across catalog, matrix, settings, and detail views.
- Discovery import into managed sites, ISO reachability validation, secret reference testing, and configurable approval policy rules.
- Approval votes with minimum approval counts, approver role checks, expiry metadata, and approval reasons.
- Job execution reports, failed/canceled job resume, richer lifecycle stage events, and drift diff output.
- Provider lab-validation evidence records surfaced in provider details and settings.
- Field installation guide and user guide for enterprise preview deployments.

### Fixed

- About page release notes now span the full content width.
- CI test dependency resolution for clean Python 3.12 GitHub Actions runners.
- GitHub Actions JavaScript runtime warning by opting the workflow into Node 24.

## [0.1.0-preview] - 2026-06-03

### Added

- Enterprise dashboard for deployments, sites, orchestration runs, providers, artifacts, lifecycle, settings, and product information.
- Password-based local login with session tokens, logout, active session listing, and server-side session revoke.
- RBAC role and user management with built-in Viewer, Operator, Deployment Admin, Platform Admin, and Auditor roles.
- Role permission picker in the dashboard.
- Audit log capture and dashboard audit view.
- Approval queue for live/high-impact actions, including approve, reject, and approve-and-run workflows.
- Job detail panel with run metadata, stage timeline, rerun action, result inspection, and authenticated live event streaming.
- PostgreSQL state backend and Redis queue support for production-style distributed execution.
- Schema migration tracking for core state, audit, approvals, job events, and provider configuration.
- Provider catalog with add, edit, remove, detail/configuration, test action, and capability matrix.
- Deployment wizard with hardware, platform, network, node editor, readiness validation, generated desired-state YAML, save, and plan actions.
- Deployment detail page with overview, nodes, runs, inventory comparison, artifacts, and lifecycle tabs.
- Artifact generation and artifact file browsing/preview for generated deployment bundles.
- Azure Local staged deployment contract.
- Lifecycle workflow contracts for drift detection and node replacement.
- Redfish inventory collection and virtual media ISO mount contract, guarded by approvals and lab-validation flags.
- Vault-backed secret provider foundations for environment, file, and HashiCorp Vault-style configuration.
- Docker Compose stack with API, dashboard, PostgreSQL, Redis, and worker services.
- Veridian/StrataOne branding in the dashboard.

### Changed

- Dashboard navigation and layout were redesigned toward an enterprise operations-console style.
- Default admin bootstrap now includes Operator permissions in addition to Platform Admin and Deployment Admin.
- Dashboard authentication now uses an in-app sign-in modal and clears stale sessions on HTTP 401 instead of prompting for a raw bearer token.
- Checkbox controls now use a polished custom visual style.
- Provider and lifecycle views are interactive instead of static placeholders.

### Fixed

- Fixed stale dashboard token handling that caused `/settings` HTTP 401 errors to render as raw settings failures.
- Fixed dashboard cache busting for updated JavaScript and CSS assets.
- Fixed role creation UX by replacing free-form-only role assignment with dropdowns and permission picker controls.
- Fixed lifecycle card text alignment.
- Fixed local dashboard port guidance by using port `8088` for the dashboard.

### Security

- Added auth enforcement by default in Docker Compose.
- Restricted CORS defaults for authenticated dashboard origins.
- Added password hashing for local users.
- Added audit events for auth, provider, approval, user, and session operations.

### Testing

- Added API tests for password login, logout/session revoke, RBAC, provider configuration, provider testing, approvals, approve-and-run, artifact listing/readback, queue behavior, Redfish inventory, secrets, validation, and job execution.
