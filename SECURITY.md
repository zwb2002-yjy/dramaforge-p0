# Security Policy

## Supported versions

Security updates are provided for the latest tagged release. Development
branches and historical P0 artifacts are not supported releases.

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
- DramaForge does not distribute InsightFace pretrained weights. Review licenses
  and provenance for all optional models, voices, fonts, and media.
