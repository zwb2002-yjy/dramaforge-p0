"""Real process death releases ownership; live and unknown files survive sweeps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from app.storage import scratch


def _writer(root: Path) -> tuple[subprocess.Popen, Path]:
    code = """
import sys, time
from pathlib import Path
from uuid import uuid4
from app.storage import scratch
scratch._root = lambda: Path(sys.argv[1])
with scratch.OwnedMediaDirectory(operation_id=uuid4()) as directory:
    (directory / 'partial.mp4').write_bytes(b'partial')
    print(directory, flush=True)
    time.sleep(60)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(root)], stdout=subprocess.PIPE, text=True
    )
    assert process.stdout is not None
    directory = Path(process.stdout.readline().strip())
    assert directory.parent == root and directory.is_dir()
    return process, directory


def test_sigkill_reclaims_only_a_dead_owner_and_preserves_concurrent_work(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch, "_root", lambda: tmp_path)
    unknown = tmp_path / "job-unknown"
    unknown.mkdir()
    (unknown / "owner.json").write_text('{"kind":"unrecognized"}')
    sentinel = tmp_path / "historical-evidence"
    sentinel.write_bytes(b"retained")
    killed, killed_directory = _writer(tmp_path)
    live, live_directory = _writer(tmp_path)
    try:
        assert scratch.sweep_owned_media() == 0
        killed.kill()
        killed.wait(timeout=10)
        assert scratch.sweep_owned_media() == 1
        assert not killed_directory.exists()
        assert live.poll() is None and (live_directory / "partial.mp4").exists()
        assert sentinel.read_bytes() == b"retained" and unknown.is_dir()
        assert scratch.sweep_owned_media() == 0
    finally:
        for process in (killed, live):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            if process.stdout:
                process.stdout.close()
        scratch.sweep_owned_media()


def test_normal_failure_removes_owned_files_and_a_sweep_cannot_collect_active_context(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(scratch, "_root", lambda: tmp_path)
    with (
        pytest.raises(ValueError, match="controlled"),
        scratch.OwnedMediaDirectory(operation_id=uuid4()) as directory,
    ):
        (directory / "download").write_bytes(b"incomplete")
        assert scratch.sweep_owned_media() == 0
        raise ValueError("controlled")
    assert not directory.exists()


def test_sweep_does_not_follow_directory_or_marker_symlinks(tmp_path, monkeypatch):
    root, retained = tmp_path / "scratch", tmp_path / "retained"
    root.mkdir()
    retained.mkdir()
    (retained / "owner.json").write_text(
        '{"kind":"dramaforge-owned-media-v1","operation_id":"' + str(uuid4()) + '"}'
    )
    (root / "job-link").symlink_to(retained, target_is_directory=True)
    marker_link = root / "job-marker-link"
    marker_link.mkdir()
    (marker_link / "owner.json").symlink_to(retained / "owner.json")
    monkeypatch.setattr(scratch, "_root", lambda: root)
    assert scratch.sweep_owned_media() == 0
    assert (retained / "owner.json").exists()


def test_local_cleanup_failure_does_not_replace_delivery_result_and_can_be_reclaimed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(scratch, "_root", lambda: tmp_path)
    owned = scratch.OwnedMediaDirectory(operation_id=uuid4())
    original = scratch.shutil.rmtree

    def fail(_directory):
        raise OSError("controlled disk cleanup failure")

    monkeypatch.setattr(scratch.shutil, "rmtree", fail)
    owned.cleanup()
    assert owned.path.exists()
    monkeypatch.setattr(scratch.shutil, "rmtree", original)
    assert scratch.sweep_owned_media() == 1
