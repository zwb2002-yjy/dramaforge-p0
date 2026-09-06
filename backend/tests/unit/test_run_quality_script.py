"""Structural tests for the container-owned quality entrypoint."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
QUALITY = REPO_ROOT / "scripts" / "run_quality.ps1"


def test_run_quality_script_delegates_to_container_gate() -> None:
    text = QUALITY.read_text(encoding="utf-8")
    assert "run_quality_in_docker.ps1" in text
    assert "@args" in text
    assert "Get-ProjectPython" not in text
    assert "pip install" not in text


def test_container_quality_script_owns_all_project_checks() -> None:
    text = (REPO_ROOT / "scripts" / "run_quality_in_docker.ps1").read_text(
        encoding="utf-8"
    )
    assert "docker compose -f docker-compose.quality.yml build" in text
    assert "backend-quality" in text
    assert "frontend-quality" in text
    assert "litellm-integration-quality" in text
