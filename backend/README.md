# DramaForge backend

FastAPI API and Arq workers for DramaForge P0.

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

The default and heavy workers are Compose services. Inspect or restart them
with `docker compose logs` and `docker compose restart`; do not install or run
the worker toolchain directly on the host.

## Quality

The Docker quality gate runs ruff, mypy, unit tests, PostgreSQL migration and
integration tests, and exports the OpenAPI contract before the frontend gate.
