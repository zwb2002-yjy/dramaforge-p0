"""Directory compliance checker tests (shipped script under scripts/)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_directory_compliance.py"


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
