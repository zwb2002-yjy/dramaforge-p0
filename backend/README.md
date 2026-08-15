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

## Run API

```powershell
$env:APP_ENV = "development"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`GET /health` should return HTTP 200.

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
