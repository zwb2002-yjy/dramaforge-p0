"""Stage B5 switchover coverage report script: reports binding coverage for the
unified path, never writes. A project is covered only with BOTH a verified
keyframe and a verified video binding."""

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


def test_switch_report_requires_both_keyframe_and_video() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    # The report must check per-purpose verified flags AND require both.
    assert "project_provider_bindings" in source
    assert "provider_model_bindings" in source
    assert "account_verified AND b.quality_gated" in source
    assert "pp.purpose = 'keyframe'" in source
    assert "pp.purpose = 'video'" in source
    assert "keyframe_verified and self.video_verified" in source
    # Read-only by construction: no INSERT/UPDATE/DELETE in the query body.
    assert "INSERT" not in source
    assert "UPDATE" not in source
    assert "DELETE" not in source


def test_project_coverage_requires_both_purposes() -> None:
    # Import the dataclass from the script to assert the combination semantics.
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("switch_report_mod", str(SCRIPT))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    only_keyframe = module.ProjectCoverage(
        project_id="1", project_name="k", workspace_id="w",
        keyframe_verified=True, video_verified=False,
    )
    only_video = module.ProjectCoverage(
        project_id="2", project_name="v", workspace_id="w",
        keyframe_verified=False, video_verified=True,
    )
    both = module.ProjectCoverage(
        project_id="3", project_name="b", workspace_id="w",
        keyframe_verified=True, video_verified=True,
    )
    assert only_keyframe.covered is False
    assert only_video.covered is False
    assert both.covered is True
