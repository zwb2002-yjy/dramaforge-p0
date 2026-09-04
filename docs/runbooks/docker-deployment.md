# Docker deployment runbook

## Supported deployment shape

The default `docker-compose.yml` is the release topology. It uses versioned
release images, publishes only the unprivileged Nginx gateway on
`127.0.0.1:8080`, and contains no source `build` instructions. PostgreSQL,
Redis, MinIO, LiteLLM, the API, dispatcher and workers remain on the Compose
network. A user host needs Docker Compose v2; it does not need Python, Node.js,
or a compiler.

This topology is intended to behave the same with Docker Compose v2 on Linux,
Windows Docker Desktop and macOS Docker Desktop. The authoritative CI quality
gate builds and tests the same containers used for the release path; a release
claim still requires the release candidate's Docker smoke test and evidence on
each claimed host.

## First start

Download and extract the complete online bundle from one GitHub Release. On
Windows PowerShell run:

```text
.\install.ps1
```

On Linux or macOS run:

```text
chmod +x install.sh
./install.sh
```

The installer verifies `release.env`, pulls the immutable release images,
generates unique secrets by running `app.install_env` inside the backend image,
and starts the stack with `--no-build`. It never invokes a host package manager.

Open `http://localhost:8080`. A clean instance lets the first person create the
Owner account. Public registration is closed after that bootstrap unless an
operator explicitly enables it.

On upgrade the installer updates only the release version, source commit and
image identities in `.env`. It preserves database credentials,
`BYOK_FERNET_KEY`, and Provider settings. Back up `.env` and the named volumes
before an upgrade; replacing the Fernet key makes saved Provider credentials
unreadable.

## Complete offline install

Use the architecture-specific offline release bundle, not the online bundle.
It contains `images.tar` with the complete runtime image set. After extracting:

```text
.\install.ps1 -Offline
```

or:

```text
./install.sh --offline
```

The installer imports `images.tar` and layers `docker-compose.offline.yml`,
whose `pull_policy: never` contract covers every service. Offline installation
means no registry access during installation. Cloud media Providers still need
network access and user credentials; this release does not claim that the full
creative workflow runs offline.

## Network and TLS boundary

The local default binds only to loopback and does not provide TLS. To place the
application behind an external HTTPS reverse proxy, set:

```dotenv
APP_ENV=production
DRAMAFORGE_BIND_ADDRESS=127.0.0.1
DRAMAFORGE_PORT=8080
DRAMAFORGE_PUBLIC_ORIGIN=https://drama.example.com
SESSION_COOKIE_SECURE=true
```

Terminate TLS at the reverse proxy and forward to `127.0.0.1:8080`. Do not
publish PostgreSQL, Redis, MinIO, LiteLLM or the API. Setting the bind address to
`0.0.0.0` exposes an unauthenticated HTTP boundary and is not a recommended
internet deployment.

## Development override

To build the complete stack from source, explicitly add the build override:

```text
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

This path is for maintainers and contributors. Ordinary installations consume
the release images and never compile source.

The following intentionally exposes infrastructure ports for local debugging.
The frontend gateway remains the only application entry; the API port 8000 is
not published:

```text
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

For source changes, rebuild the explicit build override and run the Docker
quality gate. Never use `docker-compose.dev.yml` on an untrusted network.

```text
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

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
