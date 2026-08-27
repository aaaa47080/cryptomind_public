# Security Policy

## Supported versions

Public snapshots are built from the active `develop` branch lineage. Only the
latest published snapshot is supported; please update before reporting issues.

## Reporting a vulnerability

Please do **not** open public GitHub issues for security vulnerabilities.

Use GitHub's [Private Vulnerability Reporting](../../security/advisories/new)
for this repository. Include:

- affected component / endpoint,
- reproduction steps or PoC,
- impact assessment.

We aim to acknowledge reports within 72 hours and will publish an advisory
after a fix is available.

## Deployment notes

This public snapshot intentionally excludes infrastructure and operations
material (deployment scripts, server configuration, business documents).
Production deployments run behind additional controls described in
[`docs/TRUST_DESIGN.md`](docs/TRUST_DESIGN.md); findings against the public
snapshot may not reproduce on the production service.
