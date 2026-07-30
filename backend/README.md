# DramaForge backend

FastAPI API and Arq workers for DramaForge P0.

## Container Runtime

The supported service runtime is the repository Docker Compose stack. Its
`Dockerfile` builds InsightFace 0.7.3 for CPython 3.12, includes the buffalo_l
ONNX model set, and validates `FaceAnalysis` with `CPUExecutionProvider` while
building the image. Model loading is therefore offline at container runtime.

```powershell
cd ..
docker compose build api worker-heavy
docker run --rm --entrypoint python dramaforge-api:latest -c "import json; from app.consistency.image_embed import insightface_status; print(json.dumps(insightface_status(), sort_keys=True))"
```

Expected status:

```json
{"available": true, "backend": "insightface+onnx", "embedding_dim": 512, "error": null}
```

The local venv workflow below is for application debugging. It does not copy
the container model cache or replace the Compose image validation.

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
