"""Structural contract for docker-compose.yml without requiring Docker CLI."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.yml"
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
    assert services["dispatcher"]["command"] == ["python", "-m", "app.workers.dispatcher"]
    assert services["api"]["ports"] == ["8000:8000"]
    for name in ("api", "dispatcher", "worker-default", "worker-heavy"):
        condition = services[name]["depends_on"]["migrate"]["condition"]
        assert condition == "service_completed_successfully"
    # GPU/ComfyUI must not be in the default compose file.
    assert "comfyui" not in services


def test_gpu_profile_is_optional_and_not_default() -> None:
    data = yaml.safe_load(GPU_COMPOSE.read_text(encoding="utf-8"))
    comfy = data["services"]["comfyui"]
    assert "gpu" in comfy.get("profiles", [])


def test_backend_image_declares_formal_media_and_face_runtime() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    for required in (
        "espeak-ng",
        "ffmpeg",
        "buffalo_l",
        "w600k_r50.onnx",
        "insightface==0.7.3",
    ):
        assert required in dockerfile
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
