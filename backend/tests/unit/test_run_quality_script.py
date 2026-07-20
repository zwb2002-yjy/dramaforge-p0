"""Structural tests for scripts/run_quality.ps1 toolchain selection."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
QUALITY = REPO_ROOT / "scripts" / "run_quality.ps1"


def test_run_quality_script_prefers_project_venv() -> None:
    text = QUALITY.read_text(encoding="utf-8")
    assert "Get-ProjectPython" in text
    assert "venv" in text and "python.exe" in text
    assert "& $Python -m ruff" in text
    assert "& $Python -m mypy" in text
    assert "& $Python -m pytest" in text
    assert "basetemp" in text
    assert "pytest-basetemp" in text
    assert "codex-pytest-*" in text


def test_run_quality_uses_npm_cmd_not_bare_python_for_frontend() -> None:
    text = QUALITY.read_text(encoding="utf-8")
    assert "Get-NpmCmd" in text or "npm.cmd" in text
    assert "& $Npm run lint" in text or "npm.cmd run lint" in text
