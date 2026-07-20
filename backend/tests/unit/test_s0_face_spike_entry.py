"""Drive the real S0-A spike entry script (insufficient fixtures path)."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPIKE = REPO_ROOT / "scripts" / "run_s0_face_spike.py"


def _load_spike_module():
    name = "run_s0_face_spike"
    spec = importlib.util.spec_from_file_location(name, SPIKE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass + future annotations resolve.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_spike_script_exists_on_freeze_path() -> None:
    assert SPIKE.is_file()
    assert (REPO_ROOT / "fixtures" / "images" / "character_canonical").is_dir()
    assert (REPO_ROOT / "docs" / "spikes").is_dir()


def test_spike_entry_blocked_by_fixture_writes_report(tmp_path: Path) -> None:
    """Real entry point must exit non-zero and write BLOCKED_BY_FIXTURE when empty."""
    report = tmp_path / "s0a-report.md"
    result = subprocess.run(
        [
            sys.executable,
            str(SPIKE),
            "--report",
            str(report),
            "--skip-model",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 2, combined
    assert "BLOCKED_BY_FIXTURE" in combined
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "BLOCKED_BY_FIXTURE" in text
    assert "FAR" in text
    assert "未计算" in text or "BLOCKED_BY_FIXTURE" in text
    assert "ACQUISITION.md" in text
    # No raw embedding dumps (long float sequences)
    assert re.search(r"\b0\.\d{3,},\s*0\.\d{3,},\s*0\.\d{3,}", text) is None


def test_spike_module_fixture_inventory_uses_manifest() -> None:
    mod = _load_spike_module()
    manifest = mod.Manifest.load(mod.MANIFEST_PATH)
    assert manifest.pairs_same == []
    assert manifest.pairs_diff == []
    assert manifest.anomalies == []
    ids = mod.list_image_sample_ids(mod.FIXTURE_DIR)
    assert ids == []


def test_pair_score_via_spike_import_path() -> None:
    """Ensure spike imports the same shipped face.pair_score used in production path."""
    mod = _load_spike_module()
    from app.consistency.face import EMBEDDING_DIM, pair_score

    a = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    assert mod.pair_score is pair_score
    assert pair_score(a, a) == pytest.approx(1.0)
