"""Drive the real S0-A spike entry script (insufficient fixtures path)."""

from __future__ import annotations

import importlib.util
import re
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


def test_spike_entry_without_private_images_writes_blocked_by_fixture_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A clean checkout must report the intentionally untracked images as missing."""
    mod = _load_spike_module()
    fixture_dir = tmp_path / "character_canonical"
    fixture_dir.mkdir()
    manifest_path = fixture_dir / "manifest.json"
    manifest_path.write_text(mod.MANIFEST_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    report = tmp_path / "s0a-report.md"

    monkeypatch.setattr(mod, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(mod, "MANIFEST_PATH", manifest_path)

    result = mod.main(["--report", str(report), "--skip-model"])
    output = capsys.readouterr().out

    assert result == 2
    assert "BLOCKED_BY_FIXTURE: missing image files for sample_ids:" in output
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "BLOCKED_BY_FIXTURE" in text
    assert "BLOCKED_BY_ENV" not in text
    # No raw embedding dumps (long float sequences)
    assert re.search(r"\b0\.\d{3,},\s*0\.\d{3,},\s*0\.\d{3,}", text) is None


def test_spike_module_fixture_inventory_uses_manifest(tmp_path: Path) -> None:
    mod = _load_spike_module()
    manifest = mod.Manifest.load(mod.MANIFEST_PATH)
    assert manifest.pairs_same
    assert manifest.pairs_diff
    assert manifest.anomalies

    expected_ids = mod.collect_missing_sample_ids(manifest, tmp_path)
    assert expected_ids
    for sample_id in expected_ids:
        (tmp_path / f"{sample_id}.jpg").touch()

    assert mod.list_image_sample_ids(tmp_path) == expected_ids
    assert mod.collect_missing_sample_ids(manifest, tmp_path) == []

    missing_id = expected_ids[0]
    (tmp_path / f"{missing_id}.jpg").unlink()
    assert mod.collect_missing_sample_ids(manifest, tmp_path) == [missing_id]


def test_pair_score_via_spike_import_path() -> None:
    """Ensure spike imports the same shipped face.pair_score used in production path."""
    mod = _load_spike_module()
    from app.consistency.face import EMBEDDING_DIM, pair_score

    a = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    assert mod.pair_score is pair_score
    assert pair_score(a, a) == pytest.approx(1.0)
