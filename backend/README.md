# DramaForge backend

FastAPI API and Arq workers for DramaForge P0.

## Container Runtime

The supported service runtime is the repository Docker Compose stack. Its
`Dockerfile` builds the optional InsightFace 0.7.3 Python runtime for CPython
3.12, but it does not download or bundle pretrained weights. InsightFace stays
disabled unless a deployer separately obtains appropriately licensed model
files, mounts them under the configured model root, and explicitly enables it.

```powershell
cd ..
docker compose build api worker-heavy
docker compose exec api python -c "import json; from app.consistency.image_embed import insightface_status; print(json.dumps(insightface_status(), sort_keys=True))"
```

Expected status:

```json
{"available": false, "backend": "hash_placeholder", "embedding_dim": 512, "error": "disabled by INSIGHTFACE_ENABLED=false"}
```

The hash placeholder is diagnostic fallback data, never release-grade evidence
of face or character consistency. The local venv workflow below is for
application debugging and does not change the licensed-weight boundary.

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
