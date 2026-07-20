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
    for name in ("postgres", "redis", "minio", "api", "worker-default", "worker-heavy"):
        assert name in services, f"missing service: {name}"
    assert "healthcheck" in services["postgres"]
    assert "healthcheck" in services["redis"]
    assert "healthcheck" in services["minio"]
    # GPU/ComfyUI must not be in the default compose file.
    assert "comfyui" not in services


def test_gpu_profile_is_optional_and_not_default() -> None:
    data = yaml.safe_load(GPU_COMPOSE.read_text(encoding="utf-8"))
    comfy = data["services"]["comfyui"]
    assert "gpu" in comfy.get("profiles", [])
