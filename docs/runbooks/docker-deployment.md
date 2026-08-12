# Docker deployment runbook

## Supported deployment shape

The default `docker-compose.yml` is the release topology. It builds the React
frontend into an unprivileged Nginx gateway and publishes only
`127.0.0.1:8080`. PostgreSQL, Redis, MinIO, LiteLLM, the API, dispatcher and
workers remain on the Compose network.

This topology is intended to behave the same with Docker Compose v2 on Linux,
Windows Docker Desktop and macOS Docker Desktop. CI validates source
configuration and application builds on all three operating systems; a release
claim still requires the release candidate's Docker smoke test and evidence on
each claimed host.

## First start

From the repository root:

```text
python scripts/init_env.py
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

If the host has Docker but not Python, generate `.env` without installing a
host Python runtime. PowerShell (Windows/macOS/Linux):

```text
docker run --rm -v "${PWD}:/workspace" -w /workspace python:3.12-slim python scripts/init_env.py
```

On native Linux, the equivalent shell command can add
`--user "$(id -u):$(id -g)"` before `-v` so the generated file is owned by the
current account.

Open `http://localhost:8080`. A clean instance lets the first person create the
Owner account. Public registration is closed after that bootstrap unless an
operator explicitly enables it.

Tagged releases may set `DRAMAFORGE_BACKEND_IMAGE` and
`DRAMAFORGE_FRONTEND_IMAGE` to the matching GHCR tags and run `docker compose
up -d --no-build`. Do not mix image versions; the migration container, API and
workers must use the same backend tag.

The environment bootstrap refuses to overwrite an existing `.env`. Back up the
file before an upgrade: `BYOK_FERNET_KEY` is required to decrypt existing
Provider credentials.

## Network and TLS boundary

The local default binds only to loopback and does not provide TLS. To place the
application behind an external HTTPS reverse proxy, set:

```dotenv
APP_ENV=production
DRAMAFORGE_BIND_ADDRESS=127.0.0.1
DRAMAFORGE_PORT=8080
DRAMAFORGE_PUBLIC_ORIGIN=https://drama.example.com
```

Terminate TLS at the reverse proxy and forward to `127.0.0.1:8080`. Do not
publish PostgreSQL, Redis, MinIO, LiteLLM or the API. Setting the bind address to
`0.0.0.0` exposes an unauthenticated HTTP boundary and is not a recommended
internet deployment.

## Development override

The following intentionally exposes infrastructure and API ports for local
debugging and excludes the production frontend unless its profile is selected:

```text
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
cd frontend
npm ci
npm run dev
```

Never use `docker-compose.dev.yml` on an untrusted network.

## Health and lifecycle

```text
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health
docker compose ps
docker compose logs --tail 200 api dispatcher worker-default worker-heavy
docker compose down
```

`/gateway-health` checks the gateway process. `/health` is proxied to the API
and includes its database readiness. Queue processing should additionally be
checked from service status and worker logs.

Named volumes `postgres_data`, `minio_data`, and `litellm_db_data` contain
persistent state. `docker compose down` preserves them; do not use `--volumes`
unless permanent data deletion is intended and backups have been verified.

## AIOS/AISphere handoff boundary

No authoritative AIOS application-manifest schema, health contract or lifecycle
API exists in this repository, and this release has not been installed or
verified inside AIOS. `deploy/aios/compose-adapter.example.yaml` is therefore a
neutral handoff descriptor, not an installable or certified AIOS manifest.

An AIOS integrator must map the descriptor to the platform's official schema,
inject secrets without committing them, retain the named volumes, route the
single HTTP entrypoint, and execute the same smoke checks. Compatibility must be
recorded only after a real target-environment deployment.
