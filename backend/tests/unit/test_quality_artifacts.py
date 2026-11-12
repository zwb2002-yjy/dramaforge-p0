"""Standalone verification output has the same bounded success/failure lifecycle."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "runtime_check", ROOT / "scripts/check_litellm_runtime_contract.py",
)
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.mark.parametrize("keep,failed", [(False, False), (True, False), (False, True)])
def test_verification_output_lifecycle(tmp_path, monkeypatch, keep, failed):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    output = tmp_path / "tmp" / "run"
    try:
        with check.verification_output(output, keep=keep):
            (output / "synthetic.dump").write_bytes(b"synthetic")
            if failed:
                raise RuntimeError("test failure")
    except RuntimeError:
        assert failed
    assert output.exists() is (keep or failed)


def test_output_rejects_existing_or_external_locations(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    output = tmp_path / "tmp" / "existing"
    output.mkdir(parents=True)
    sentinel = output / "keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError), check.verification_output(output):
        pass
    with pytest.raises(ValueError), check.verification_output(tmp_path / "outside"):
        pass
    assert sentinel.read_text() == "keep"


def test_replaced_directory_is_not_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    output = tmp_path / "tmp" / "run"
    with pytest.raises(RuntimeError, match="ownership changed"), check.verification_output(output):
        output.rename(output.with_name("original"))
        output.mkdir()
        (output / "foreign.txt").write_text("keep")
    assert (output / "foreign.txt").read_text() == "keep"


def test_nested_link_preserves_external_files(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    output = tmp_path / "tmp" / "run"
    with pytest.raises(RuntimeError, match="link"), check.verification_output(output):
        (output / "linked").symlink_to(outside, target_is_directory=True)
    assert (outside / "keep.txt").read_text() == "keep"
