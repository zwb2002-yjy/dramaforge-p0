# DEPLOYMENT — 部署权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

## Supported deployment shape

The default `docker-compose.yml` is the current `dramaforge-dev` topology. Local
images are built from current source through `docker-compose.build.yml`; future
release bundles supply immutable image references. It publishes only the unprivileged Nginx gateway on
`127.0.0.1:8080`, and contains no source `build` instructions. PostgreSQL,
Redis, MinIO, LiteLLM, the API, dispatcher and workers remain on the Compose
network. A packaged-release host needs Docker Compose v2; it does not need
Python, Node.js, or a compiler. The source-development setup below invokes
`scripts/init_env.py` and therefore needs Python for that step.

This topology is intended to behave the same with Docker Compose v2 on Linux,
Windows Docker Desktop and macOS Docker Desktop. The authoritative CI quality
gate builds and tests the same containers used for the release path; a release
claim still requires the release candidate's Docker smoke test and evidence on
each claimed host.

## Current development start

Generate a unique local environment, set the exact source commit, and build the current images:

```text
python scripts/init_env.py
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

The project is unreleased. Retain old instance volumes separately; current startup does not
reuse another worktree, old image tags or queued provider tasks.

### Frontend hot reload and backend identity

A frontend source bind mount or Vite hot reload updates only browser code. It does not
rebuild or replace the API, dispatcher, workers, or database migrations. After a change that
requires a new API, build the current images, apply the current migration chain, and update
the application services together, using the same source identity. Preserve credentials,
volumes and existing execution records; never resubmit old Provider operations during rollout.

Before reporting a local workflow fixed, check `/health` through the actual browser gateway
and compare `source_commit` with the deployed image identity. Check the dispatcher and each
worker image too, then exercise the affected API from that browser page. Source tests or
a working frontend hot reload alone do not establish that the running backend has the change.

## Future packaged release start

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
Initialization also generates a separate `DIRECTOR_CHECKPOINT_PASSWORD` and
its local `DIRECTOR_CHECKPOINT_DATABASE_URL`; the release workflow supplies
the checkpoint password explicitly when validating and smoke-testing Compose.

Open `http://localhost:8080`. A clean instance lets the first person create the
Owner account. Public registration is closed after that bootstrap unless an
operator explicitly enables it.

On upgrade the installer updates only the release version, source commit and
image identities in `.env`. It preserves database credentials,
`BYOK_FERNET_KEY`, and Provider settings. Back up `.env` and the named volumes
before an upgrade; replacing the Fernet key makes saved Provider credentials
unreadable.

PostgreSQL connections use `DATABASE_SSL=false` for the local Compose network.
Set it to `true` when the database endpoint requires TLS; the setting is passed
to the API, dispatcher and Workers and is not encoded in application code.

## Complete offline install

Use the architecture-specific offline release bundle, not the online bundle.
It contains `images.tar.gz` with the complete runtime image set. Extract it into
a directory and run the installer from that same directory (the archive holds the
installer, `release.env`, the Compose files and the image archive at its top
level):

```text
.\install.ps1 -Offline
```

or:

```text
./install.sh --offline
```

The installer imports `images.tar.gz` and layers `docker-compose.offline.yml`,
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

## Provider connection security boundary

DramaForge Provider HTTP clients (including poll/cancel) connect directly with
`trust_env=False`; `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` do not route these
calls. These variables are available to Proxy-side upstream access and build
tools. `PROVIDER_TRUSTED_HTTP_NETWORKS` authorizes only declared private HTTP
endpoints; it does not configure a forward proxy. HTTP connection pools belong
to the API/worker event loop and close at shutdown. Headers and cookies remain
local to each request client.

The public Nginx gateway limits login and registration together to five requests
per minute per remote address, allowing a burst of five, and returns 429 on
excess requests with `AUTH_RATE_LIMITED` Problem Details and `Retry-After: 12`.
The quota uses the TCP peer address; client-supplied `X-Forwarded-For` / `X-Real-IP`
never select a different quota. Uvicorn's shipped commands disable proxy headers.
If an additional reverse proxy is placed before this gateway, its clients share
the proxy's quota by default. Trusting a separately controlled proxy requires an
explicit Nginx real-IP policy for its exact addresses/networks and a forwarding-chain
test; do not enable blanket header trust or publish the internal API as a bypass.
Unknown and inactive accounts perform the same password KDF as a known account,
and failed logins have the same public error. `/metrics` is available on the internal API listener; Nginx
does not forward it. `/worker/tick` requires development mode and the worker
token; production and test reject it.

Workspace-supplied Provider connections send their encrypted credentials to
the configured `base_url` through the server-side guarded transport; a supported
media connection with explicit `auth_mode=none` sends no Authorization header.
New text connections instead store the internal Proxy address and restricted
data credential. Their upstream address/key are registered through the existing
workspace management API and stored by the Proxy, never used as an application
direct-call fallback.
The boundary is layered — write-time static validation, then connection-time
egress enforcement:

- `PROVIDER_BASE_URL_ALLOW_PRIVATE` (default `false`): connection base URLs
  must be public HTTPS origins. Private/loopback IP literals are rejected
  unless an operator explicitly sets this to `true` for an authenticated
  self-hosted private deployment. Link-local, multicast, unspecified,
  reserved and shared (CGNAT) destinations are rejected regardless — they
  are credential-exfiltration primitives, not private deployments. Reserved
  addresses that Python also classifies as private (for example `240.0.0.1`)
  stay blocked even when private deployments are authorized.
- `PROVIDER_TRUSTED_HTTP_NETWORKS` (default empty): scoped plaintext-HTTP
  trust for local model deployments, e.g.
  `PROVIDER_TRUSTED_HTTP_NETWORKS=172.18.6.0/24` then a connection
  `base_url` of `http://172.18.6.80:30020`. HTTP is accepted only for IP
  literals inside a declared network; a whole-address-space entry (`/0`) is
  rejected at startup. Named hosts over HTTP are rejected — terminate TLS on
  a reverse proxy, or address the service by IP. This is deliberately a
  separate, narrower trust than the global private opt-in above.
- Connection-time egress enforcement: every provider TCP connection (probe,
  submit, poll, cancel) resolves its destination, classifies every resolved
  address with the same rules, and opens the socket against one validated
  address. A hostname that resolves to a private or reserved target fails
  closed before credentials leave the process; DNS-rebinding cannot redirect
  an in-flight connection because the socket is pinned to the validated
  address. Connections saved under an earlier policy are re-validated on
  every new socket.
  DNS resolution and TCP attempts share the connect timeout. If an address
  cannot establish a socket, other addresses in the same validated answer
  set may be tried before any HTTP bytes are sent; no request is replayed.
  Every request also rechecks the URL before entering the pool, including old
  stored URLs; the private opt-in alone cannot authorize plaintext HTTP.
  Historical workspace text probes use this guard too. The operator-configured
  internal LiteLLM Proxy URL retains its separate deployment trust boundary.
- `REFERENCE_PUBLIC_BASE_URL` (default empty): public HTTPS API origin used
  for short-lived signed Provider references. Models whose wire contract
  consumes public URLs (Ark, MiniMax, Agnes video contract revisions) issue
  these grants from the Worker; without this setting those reference-bearing
  generations fail closed with `REFERENCE_DELIVERY_NOT_CONFIGURED` instead of
  silently degrading.

## PostgreSQL connection budget

`docker-compose.yml` sets `max_connections=160` on PostgreSQL and sizes each
service role's engine pool explicitly: api `DB_POOL_SIZE=20` +
`DB_MAX_OVERFLOW=10`, dispatcher `3+2`, worker-default `10+5`,
worker-director `4+2`, worker-heavy `5+5`. At one process per listed role,
the application engine ceilings sum to 66. The remaining capacity must also
cover Director checkpoint pools, migrations, maintenance, PostgreSQL reserved
slots and every other client; `160` is a deployment setting, not a general
capacity guarantee.

Scaling changes the arithmetic: every additional API or Worker replica, a
larger checkpoint pool, or extra administrative clients (analytics, manual
`psql` sessions) consumes from the same `max_connections` budget. Recompute
the per-role values (and raise `max_connections`) before adding replicas —
exhaustion surfaces as pool checkout timeouts, not as queue backlog.

## Health and lifecycle

```text
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health
docker compose ps
docker compose logs --tail 200 api dispatcher worker-default worker-director worker-heavy
docker compose down
```

`/gateway-health` checks the gateway process. `/health` is proxied to the API
and includes its database readiness. Queue processing should additionally be
checked from service status and worker logs: `worker-default` consumes
`dramaforge:default`, `worker-director` consumes `dramaforge:director`
(Director turns, event intake and wakeup replay), and `worker-heavy` consumes
`dramaforge:heavy`. Recoverable work is republished by the resident
`dispatcher` and by the Director worker's startup recovery.
Provider reconciliation runs in an independent dispatcher loop, not a heavy-queue cron job;
media execution still uses the existing queue. Apply migrations through the
candidate head (see [DATA_MODEL.md](DATA_MODEL.md); confirm with `alembic heads`) before
updating the dispatcher and media workers. This rollout is not implied by a source-only push.

The current unreleased schema has a one-way cleanup head (see [DATA_MODEL.md](DATA_MODEL.md)).
Use a fresh development database and retain old environment volumes separately. Do not translate
old queued requests, relabel old image identities, or stamp past unapplied migrations.

PostgreSQL, Redis, MinIO and the LiteLLM database use `restart: unless-stopped` plus bounded
startup health periods. The API, dispatcher and every Worker wait for PostgreSQL health and
the completed database bootstrap, then also restart unless explicitly stopped. The frontend
waits for API health. This ordering prevents a surviving gateway from presenting an API that
started before its DNS/database dependencies recovered after a Docker restart.

Director health uses `python -m app.workers.healthcheck` rather than importing
all WorkerSettings/jobs for the Arq CLI. It checks the configured queue's nonempty
Redis heartbeat plus a positive TTL of at most 3,601,000ms (not Redis PING), with
no retries and a 3-second total probe deadline; Docker's timeout remains 5 seconds.
Arq's existing 3600-second refresh / 3601-second expiry window is unchanged. This
is **queue-level liveness, not per-process readiness**: another worker on the same
queue can maintain the heartbeat. Check worker logs and actual job progress when
diagnosing an individual process.

The LiteLLM process shares the network namespace of `litellm-network`, which
reuses the backend image and has only the NET_ADMIN capability required to
install its own default-deny rules. The Proxy has no capabilities. This does
not alter the host firewall or media workers. Exact authorized origins and
trusted private/plaintext CIDRs come from `LITELLM_EGRESS_ALLOWED_ORIGINS` and
`LITELLM_EGRESS_TRUSTED_NETWORKS` JSON lists; defaults allow no model upstream.
All DNS answers are validated and pinned to IP/port rules until the namespace
is recreated. Recreate the guard and Proxy together when grants or DNS change.
Development publishes port 4000 on the namespace owner, never the shared Proxy.

Keep `LITELLM_SALT_KEY` stable with the Proxy DB backup. For an old database
encrypted using the Master fallback, preserve and verify the original effective
salt before enabling DB management. Never generate a replacement salt over
existing ciphertext. The single-worker pinned Proxy rejects duplicate YAML/DB
aliases, request-level transport overrides and shadow calls; HTTPX, requests and
aiohttp do not follow redirects. Prisma's local control channel uses fixed
port 4001 rather than a broad loopback port grant. Admin and data keys remain
separate. The one-shot trusted `litellm-bootstrap` provisions restricted service
keys without upstream calls or secret output. Only the API receives the model
management key; generation workers do not. The API keeps existing workspace
ownership/RLS and CSRF enforcement, while the Proxy enforces immutable managed
targets and monotonic credential revisions. This is restricted credentials in
the same API process, not full management-process isolation.

New text execution requires a ready workspace-owned managed reference. Keep
historical connection and credential revisions, BYOK key versions, original
resume tokens and frozen contracts. Static YAML aliases remain isolated from
new managed aliases and cannot be selected for new production. Do not infer
an old alias's physical deployment from its name or automatically remap an old
profile. A queued old plan without its required identity stays blocked for
explicit review; a possibly submitted operation is never resubmitted.

Back up both application and Proxy databases with their schema/image versions
and matching encryption keys before migration. The current head is recorded
in [DATA_MODEL.md](DATA_MODEL.md). Model reference/auth migrations refuse a
downgrade when it would discard retained references or no-auth facts; an
application rollback must still understand the data already written. Restore
and verify a separate copy first. Preserving a volume without its effective
SALT/BYOK keys is not a usable rollback.

Schema upgrade and catalog publication are separate maintenance steps. New
file-backed contracts are not inserted automatically by the API or by replaying
old frozen seed migrations. With the matching source and backend image, compare
the catalog first, then explicitly apply it using the maintenance database role:

```bash
docker compose --profile maintenance run --rm --entrypoint python maintenance /workspace/scripts/sync_model_catalog.py
docker compose --profile maintenance run --rm --entrypoint python maintenance /workspace/scripts/sync_model_catalog.py --apply
```

This appends exact contract revisions and synchronizes publication state. An
existing identity with a different hash is rejected; historical JSON, hashes,
Bindings and execution identities are never rewritten. Ordinary API/Worker
roles remain read-only for the catalog.

Media protocol admission is independent of text Proxy health. Choose only an
installed versioned wire contract; service URL/model ID remain connection and
Binding data. Discovery, contract checks, revision-specific generated Artifacts,
browser playback and quality review are separate evidence. An unknown response
shape, unsupported encoding or false duration must block the corresponding
service acceptance rather than silently transcode, change the request or certify
advanced capabilities. Live generation requires its own current Owner contract;
mock/contract gates do not authorize a live create or a remote service restart.

Named volumes `postgres_data`, `minio_data`, and `litellm_db_data` contain
persistent state. `docker compose down` preserves them; do not use `--volumes`
unless permanent data deletion is intended and backups have been verified.
Backup and restore-verify run through the profiled maintenance service, whose
entrypoint is `scripts/p0_backup_restore.py` (see
[DEVELOPMENT.md](DEVELOPMENT.md)).

## Director runtime engine

`DIRECTOR_RUNTIME_ENGINE` only accepts `langgraph`. Both API and worker-director receive
`DIRECTOR_CHECKPOINT_DATABASE_URL`; the dedicated checkpoint password is required and
`database-bootstrap` provisions the private schema role. Worker startup verifies the store.
Manual production remains available independently of the Director worker.

## AIOS/AISphere handoff boundary

No authoritative AIOS application-manifest schema, health contract or lifecycle
API exists in this repository, and this release has not been installed or
verified inside AIOS. `deploy/aios/compose-adapter.example.yaml` is therefore a
neutral handoff descriptor, not an installable or certified AIOS manifest.

An AIOS integrator must map the descriptor to the platform's official schema,
inject secrets without committing them, retain the named volumes, route the
single HTTP entrypoint, and execute the same smoke checks. Compatibility must be
recorded only after a real target-environment deployment.
