"""Regression guards for the Windows-to-WSL local stack launcher."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_powershell_launcher_is_ascii_and_uses_its_own_directory() -> None:
    launcher = REPO_ROOT / "scripts" / "start_p0_stack.ps1"
    raw = launcher.read_bytes()

    # Windows PowerShell 5.1 can parse a UTF-8 script as the active ANSI code
    # page. Keeping path-bearing launcher source ASCII prevents path corruption.
    raw.decode("ascii")
    text = raw.decode("ascii")
    assert "$PSScriptRoot" in text
    assert "bash scripts/start_p0_wsl_stack.sh" in text
    assert "D:\\" not in text


def test_wsl_launcher_uses_systemd_restart_not_a_readiness_kill_loop() -> None:
    launcher = (REPO_ROOT / "scripts" / "start_api_wsl_stable.sh").read_text(encoding="utf-8")

    assert "systemd-run --user" in launcher
    assert "--property=Restart=on-failure" in launcher
    assert "alembic -c alembic.ini upgrade head" in launcher
    assert "prepare)" in launcher
    assert "while true" not in launcher


def test_windows_api_mode_prepares_wsl_database_and_only_stops_owned_processes() -> None:
    launcher = (REPO_ROOT / "scripts" / "start_p0_stack.ps1").read_text(encoding="ascii")

    assert 'Invoke-WslStack "prepare"' in launcher
    assert "Test-OwnedWindowsApi" in launcher
    assert "Stop-OwnedWindowsApi" in launcher


def test_standalone_dispatcher_registers_complete_model_graph() -> None:
    launcher = (REPO_ROOT / "scripts" / "start_p0_wsl_stack.sh").read_text(
        encoding="utf-8"
    )
    assert "load_all_models()" in launcher

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "backend")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.shared.model_registry import load_all_models;"
                "load_all_models();"
                "from app.events.models import OutboxEvent;"
                "fk=next(iter(OutboxEvent.__table__.c.project_id.foreign_keys));"
                "print(fk.column.table.name)"
            ),
        ],
        cwd=REPO_ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "projects"
