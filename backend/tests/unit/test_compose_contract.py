"""Structural contract for docker-compose.yml without requiring Docker CLI."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.yml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
GPU_COMPOSE = REPO_ROOT / "docker-compose.gpu.yml"


def test_compose_defines_required_boot0_services() -> None:
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = data["services"]
    for name in (
        "postgres",
        "redis",
        "minio",
        "migrate",
        "api",
        "dispatcher",
        "worker-default",
        "worker-heavy",
        "frontend",
    ):
        assert name in services, f"missing service: {name}"
    assert "healthcheck" in services["postgres"]
    assert "healthcheck" in services["redis"]
    assert "healthcheck" in services["minio"]
    provider_env = {
        "AGNES_ENABLED",
        "AGNES_API_KEY",
        "AGNES_BASE_URL",
        "AGNES_IMAGE_MODEL",
        "AGNES_VIDEO_MODEL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "TEXT_LLM_ENABLED",
        "TEXT_LLM_API_KEY",
        "TEXT_LLM_BASE_URL",
        "TEXT_LLM_MODEL",
        "TEXT_LLM_API_STYLE",
        "TTS_ENABLED",
        "TTS_ENGINE",
        "TTS_VOICE",
    }
    for name in ("api", "worker-default", "worker-heavy"):
        env = services[name]["environment"]
        assert provider_env <= set(env), f"missing runtime provider config in {name}"
        assert "DRAMAFORGE_SOURCE_COMMIT" in env
    assert "ARQ_HEAVY_MAX_JOBS" in services["worker-heavy"]["environment"]
    assert services["dispatcher"]["command"] == ["python", "-m", "app.workers.dispatcher"]
    externally_published = {
        name: service.get("ports", []) for name, service in services.items()
    }
    assert externally_published["frontend"] == [
        "${DRAMAFORGE_BIND_ADDRESS:-127.0.0.1}:${DRAMAFORGE_PORT:-8080}:8080"
    ]
    assert all(
        not ports for name, ports in externally_published.items() if name != "frontend"
    )
    assert services["frontend"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["frontend"]["image"] == (
        "${DRAMAFORGE_FRONTEND_IMAGE:-dramaforge-frontend:local}"
    )
    assert services["frontend"]["read_only"] is True
    assert services["frontend"]["cap_drop"] == ["ALL"]
    for name in ("api", "dispatcher", "worker-default", "worker-heavy"):
        condition = services[name]["depends_on"]["migrate"]["condition"]
        assert condition == "service_completed_successfully"
        assert services[name]["security_opt"] == ["no-new-privileges:true"]
        assert services[name]["cap_drop"] == ["ALL"]
        assert "healthcheck" in services[name]
        assert services[name]["image"] == (
            "${DRAMAFORGE_BACKEND_IMAGE:-dramaforge-backend:local}"
        )
    # GPU/ComfyUI must not be in the default compose file.
    assert "comfyui" not in services


def test_gpu_profile_is_optional_and_not_default() -> None:
    data = yaml.safe_load(GPU_COMPOSE.read_text(encoding="utf-8"))
    comfy = data["services"]["comfyui"]
    assert "gpu" in comfy.get("profiles", [])


def test_development_override_exposes_debug_ports_and_disables_production_ui() -> None:
    services = yaml.safe_load(DEV_COMPOSE.read_text(encoding="utf-8"))["services"]
    assert services["api"]["ports"] == ["8000:8000"]
    assert services["postgres"]["ports"] == ["5432:5432"]
    assert services["redis"]["ports"] == ["6379:6379"]
    assert services["minio"]["ports"] == ["9000:9000", "9001:9001"]
    assert services["litellm"]["ports"] == ["4000:4000"]
    assert services["frontend"]["profiles"] == ["production-ui"]


def test_backend_image_declares_formal_media_and_face_runtime() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    for required in ("espeak-ng", "ffmpeg", "insightface==0.7.3"):
        assert required in dockerfile
    assert "github.com/deepinsight/insightface/releases" not in dockerfile
    assert "w600k_r50.onnx" not in dockerfile
    assert "FaceAnalysis(name=" not in dockerfile
    for required in (
        "onnx",
        "onnxruntime",
        "opencv-python-headless",
        "scikit-image",
        "scikit-learn",
        "albumentations",
        "matplotlib",
        "prettytable",
        "easydict",
    ):
        assert required in pyproject
    assert "USER 10001:10001" in dockerfile


def test_frontend_image_is_static_unprivileged_gateway() -> None:
    dockerfile = (REPO_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (REPO_ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "npm run build" in dockerfile
    assert "nginx-unprivileged" in dockerfile
    assert "EXPOSE 8080" in dockerfile
    assert "proxy_pass http://api:8000" in nginx
    assert "try_files $uri $uri/ /index.html" in nginx


def test_compose_requires_unique_runtime_secrets_and_disables_public_registration() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    assert services["litellm"]["environment"]["LITELLM_MASTER_KEY"].startswith(
        "${LITELLM_MASTER_KEY:?"
    )
    api_env = services["api"]["environment"]
    for name in ("SESSION_SECRET", "WORKER_TOKEN", "BYOK_FERNET_KEY"):
        assert api_env[name].startswith(f"${{{name}:?")
    assert api_env["PUBLIC_REGISTRATION_ENABLED"] == "${PUBLIC_REGISTRATION_ENABLED:-false}"
    for service_name in ("migrate", "api", "dispatcher", "worker-default", "worker-heavy"):
        service_env = services[service_name]["environment"]
        assert service_env["BYOK_FERNET_KEY"].startswith("${BYOK_FERNET_KEY:?")
        assert service_env["WORKER_TOKEN"].startswith("${WORKER_TOKEN:?")
        assert service_env["APP_ENV"] == "${APP_ENV:-development}"
    assert services["postgres"]["environment"]["POSTGRES_PASSWORD"].startswith(
        "${POSTGRES_PASSWORD:?"
    )
    assert services["minio"]["environment"]["MINIO_ROOT_PASSWORD"].startswith(
        "${MINIO_ROOT_PASSWORD:?"
    )
    compose_text = COMPOSE.read_text(encoding="utf-8")
    for forbidden in (
        "dev-only-change-me-to-a-long-random-string",
        "dev-only-fernet-key-replace-in-prod==",
        "sk-dev-change-me",
    ):
        assert forbidden not in compose_text
