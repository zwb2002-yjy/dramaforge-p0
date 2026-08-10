"""Stage B5 switchover coverage report script: reports binding coverage for the
unified path, never writes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "provider_unified_switch_report.py"


def test_switch_report_script_imports_without_connecting() -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path({str(SCRIPT)!r})"],
        check=False,
        capture_output=True,
        text=True,
    )
    # Import succeeds (no DATABASE_URL connection attempted at import).
    assert result.returncode == 0, result.stderr


def test_switch_report_queries_binding_coverage() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    # The report must look at Project/Model bindings + the four evidence flags.
    assert "project_provider_bindings" in source
    assert "provider_model_bindings" in source
    assert "account_verified AND b.quality_gated" in source
    # Read-only by construction: no INSERT/UPDATE/DELETE in the query body.
    assert "INSERT" not in source
    assert "UPDATE" not in source
    assert "DELETE" not in source
