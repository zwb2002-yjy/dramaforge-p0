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

## Local setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Run the application

```powershell
cd ..
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Open `http://127.0.0.1:8080`. The API listens on container-only port 8000 and
is not published as a separate host application entry. For backend-only
diagnostics, run Uvicorn inside the API container on its existing port 8000.

## Run workers (requires Redis)

```powershell
python -m app.workers.main default
arq app.workers.default.WorkerSettings

python -m app.workers.main heavy
arq app.workers.heavy.WorkerSettings
```

## Quality

```powershell
python -m ruff check app tests
python -m mypy app
python -m pytest -q
```
