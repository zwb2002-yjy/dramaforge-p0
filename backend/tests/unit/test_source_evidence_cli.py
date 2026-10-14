"""Offline maintenance preserves prior provenance records and frozen manifests."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from shutil import copytree

import pytest
from app.providers.catalog_loader import ModelCatalogLoader


def _cli():
    script = Path(__file__).resolve().parents[3] / "scripts/model_source_evidence.py"
    spec = importlib.util.spec_from_file_location("source_evidence_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy(tmp_path):
    source = Path(__file__).resolve().parents[2] / "app/providers/model_sources"
    root = tmp_path / "sources"
    copytree(source, root)
    return root


def test_check_append_preserves_old_records_snapshots_and_all_manifest_hashes(
    tmp_path, monkeypatch
):
    root = _copy(tmp_path)
    before_checks = json.loads((root / "source_checks.json").read_text())["checks"]
    before_snapshots = (root / "source_snapshots.json").read_bytes()
    manifests = [(item.identity, item.manifest_hash) for item in ModelCatalogLoader().load()]
    record = {
        "check_id": "explicit-offline-review",
        "source_snapshot_ref": before_checks[0]["source_snapshot_ref"],
        "checked_at": "2026-10-13T00:00:00+08:00",
        "result": "temporary_error",
        "note": "Offline fixture",
    }
    path = tmp_path / "check.json"
    path.write_text(json.dumps(record))
    module = _cli()
    monkeypatch.setattr(
        sys, "argv", ["source", "--root", str(root), "check", "--record-json", str(path)]
    )
    assert module.main() == 0
    after = json.loads((root / "source_checks.json").read_text())["checks"]
    assert after[:-1] == before_checks
    assert (root / "source_snapshots.json").read_bytes() == before_snapshots
    assert [
        (item.identity, item.manifest_hash) for item in ModelCatalogLoader().load()
    ] == manifests
    unchanged = (root / "source_checks.json").read_bytes()
    assert module.main() == 0
    assert (root / "source_checks.json").read_bytes() == unchanged


def test_snapshot_append_requires_real_body_and_rejects_rewriting_same_identity(
    tmp_path, monkeypatch
):
    root = _copy(tmp_path)
    old = json.loads((root / "source_snapshots.json").read_text())["snapshots"]
    body = tmp_path / "body.txt"
    body.write_bytes(b"controlled source capture")
    record = {
        "source_snapshot_id": "controlled-body-v1",
        "source_id": old[0]["source_id"],
        "capture_status": "captured",
        "content_sha256": hashlib.sha256(body.read_bytes()).hexdigest(),
        "locator": "fixture",
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(record))
    module = _cli()
    args = ["source", "--root", str(root), "snapshot", "--record-json", str(path)]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(ValueError, match="actual hash-matching"):
        module.main()
    assert not (root / ".source-metadata.lock").exists()
    monkeypatch.setattr(sys, "argv", [*args, "--body", str(body)])
    assert module.main() == 0
    assert json.loads((root / "source_snapshots.json").read_text())["snapshots"][:-1] == old
    original = (root / "source_snapshots.json").read_bytes()
    body.write_bytes(b"changed source")
    record["content_sha256"] = hashlib.sha256(body.read_bytes()).hexdigest()
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="cannot be rewritten"):
        module.main()
    assert (root / "source_snapshots.json").read_bytes() == original


def test_other_writer_lock_is_preserved_and_metadata_remains_unchanged(tmp_path, monkeypatch):
    root = _copy(tmp_path)
    lock = root / ".source-metadata.lock"
    lock.write_text("another writer")
    before = (root / "source_checks.json").read_bytes()
    module = _cli()
    monkeypatch.setattr(
        sys, "argv", ["source", "--root", str(root), "check", "--record-json", "unused"]
    )
    with pytest.raises(FileExistsError):
        module.main()
    assert lock.read_text() == "another writer"
    assert (root / "source_checks.json").read_bytes() == before
