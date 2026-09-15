# DramaForge backend

FastAPI API, domain services, Arq workers and Alembic migrations for DramaForge.
The backend owns the canonical creation facts and the single production runtime;
the Director runtime orchestrates turns without owning media.

## Container Runtime

The supported service runtime is the repository Docker Compose stack. The
first release has no biometric embedding or face-similarity runtime. Character
identity evidence is built from Canonical reference binding, the effective
Provider request, immutable Artifacts, sampled video frames and audited human
trial review.

```powershell
cd ..
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

## Development dependencies

No host Python environment is required. The backend dependencies and all
backend checks are installed and executed by the repository quality image:

```powershell
cd ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

## Run the application

```powershell
cd ..
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Open `http://127.0.0.1:8080`. The API listens on container-only port 8000 and
is not published as a separate host application entry. For backend-only
diagnostics, run Uvicorn inside the API container on its existing port 8000.

## Run workers

The default, director and heavy workers are Compose services. Inspect or restart
them with `docker compose logs` and `docker compose restart`; do not install or
run the worker toolchain directly on the host.

| Service | Queue | Role |
|---|---|---|
| `worker-default` | `dramaforge:default` | media, review and continuity jobs |
| `worker-director` | `dramaforge:director` | bounded Director turns, event intake and wakeup replay; Provider calls disabled |
| `worker-heavy` | `dramaforge:heavy` | heavy media jobs |
| `dispatcher` | — | resident transactional-Outbox dispatcher |

Each worker first runs `python -m app.workers.main <kind>` to print its
ready line, then starts `arq app.workers.<kind>.WorkerSettings`.

## Quality

The Docker quality gate runs directory and canonical-surface scans, ruff, mypy,
unit tests, PostgreSQL migration and integration tests, and exports the OpenAPI
contract before the frontend gate.
