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
