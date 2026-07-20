# DramaForge backend

FastAPI API and Arq workers for DramaForge P0.

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
