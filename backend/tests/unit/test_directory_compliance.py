"""Directory compliance checker tests (shipped script under scripts/)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_directory_compliance.py"


def test_disk_scan_prunes_caches_without_hiding_source_secrets(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("directory_compliance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for relative in ("tmp/evidence", "frontend/node_modules/package", "backend/app/data", "backend/app/logs"):
        (tmp_path / relative).mkdir(parents=True)
    (tmp_path / ".env").write_text("local synthetic settings")
    (tmp_path / "backend/.env").write_text("synthetic secret")
    (tmp_path / "backend/app/credentials.json").write_text("{}")
    (tmp_path / "backend/app/test.key").write_text("synthetic key")
    (tmp_path / "backend/app/data/.env").write_text("synthetic nested secret")
    (tmp_path / "backend/app/logs/test.key").write_text("synthetic nested key")
    original = os.scandir

    def guarded_scan(path):
        assert "node_modules" not in Path(path).relative_to(tmp_path).parts
        assert "tmp" not in Path(path).relative_to(tmp_path).parts
        return original(path)

    monkeypatch.setattr(os, "scandir", guarded_scan)
    errors = module.check_sensitive_on_disk(tmp_path)
    assert len(errors) == 5
    assert any("backend/.env" in error for error in errors)
    assert any("backend/app/credentials.json" in error for error in errors)
    assert any("backend/app/test.key" in error for error in errors)
    assert any("backend/app/data/.env" in error for error in errors)
    assert any("backend/app/logs/test.key" in error for error in errors)


def test_directory_compliance_passes_on_repo() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(REPO_ROOT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Directory compliance OK" in result.stdout


def test_directory_compliance_rejects_demo_unregistered_and_sensitive() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(REPO_ROOT),
            "--demo-unregistered",
            "utils2",
            "--demo-sensitive",
            ".env",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REJECT unregistered: utils2" in result.stdout
    assert "REJECT sensitive/build: .env" in result.stdout


def test_local_ide_artifacts_are_allowed_on_disk_but_rejected_in_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    artifact = tmp_path / ".trae-html-share-packages" / "preview.html"
    artifact.parent.mkdir()
    artifact.write_text("local preview", encoding="utf-8")
    command = [sys.executable, str(SCRIPT), "--root", str(tmp_path)]
    local = subprocess.run(command, capture_output=True, text=True, check=False)
    assert local.returncode == 0, local.stdout + local.stderr
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    tracked = subprocess.run(command, capture_output=True, text=True, check=False)
    assert tracked.returncode != 0
    assert "forbidden path tracked by git" in tracked.stdout + tracked.stderr


def test_playwright_results_are_local_only_and_cannot_be_tracked(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    trace = tmp_path / "test-results" / "playwright" / "trace.zip"
    trace.parent.mkdir(parents=True)
    trace.write_bytes(b"temporary test result")
    report = tmp_path / "playwright-report" / "index.html"
    report.parent.mkdir()
    report.write_text("test report", encoding="utf-8")
    command = [sys.executable, str(SCRIPT), "--root", str(tmp_path)]
    local = subprocess.run(command, capture_output=True, text=True, check=False)
    assert local.returncode == 0, local.stdout + local.stderr

    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", "test-results/playwright/trace.zip"],
        check=True,
    )
    tracked = subprocess.run(command, capture_output=True, text=True, check=False)
    assert tracked.returncode != 0
    assert "forbidden path tracked by git" in tracked.stdout + tracked.stderr
