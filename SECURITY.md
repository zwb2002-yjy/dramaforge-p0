# Security Policy

## Supported versions

There is no tagged release yet, so no released version is currently in a
supported security-maintenance window. Reports against the current code are
accepted and fixes follow the protected `dev` to `main` integration path. This
section will name supported version ranges when the first release is tagged.

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities. Use GitHub's private
security advisory feature for this repository. Include affected versions,
reproduction steps, impact, and any suggested mitigation. Do not include real
credentials, private user media, or exploit data belonging to another person.

The maintainer will acknowledge a complete report as soon as practical,
coordinate validation and remediation privately, and publish an advisory when a
fix is available. No fixed response deadline or bounty is promised.

## Deployment boundary

- The default Compose stack exposes only the frontend gateway. It does not add TLS;
  internet-facing operators must terminate HTTPS at a trusted external proxy.
- Public registration is disabled by default after first-Owner bootstrap.
- Generate unique local secrets with `python scripts/init_env.py`; preserve the
  BYOK Fernet key across upgrades and use the rotation tooling for changes.
- Do not expose PostgreSQL, Redis, MinIO, LiteLLM, or the API directly to untrusted
  networks. `docker-compose.dev.yml` opens debug ports and is for local development.
- Review licenses and provenance for all optional models, evaluators, voices,
  fonts, and media.
