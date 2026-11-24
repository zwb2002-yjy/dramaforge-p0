"""Pure safety checks for encrypted recovery archive handling."""

from __future__ import annotations

import importlib.util
import tarfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "p0_backup_restore.py"
spec = importlib.util.spec_from_file_location("p0_backup_restore", SCRIPT)
assert spec is not None and spec.loader is not None
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_legacy_inspection_verifies_declared_bytes_without_modifying_files(tmp_path, monkeypatch):
    import hashlib
    import io
    import json

    key = Fernet.generate_key()
    monkeypatch.setenv("TEST_LEGACY_KEY", key.decode())
    for content, valid in [(b"synthetic", True), (b"damaged", False)]:
        data = b"PGDMP synthetic"

        def h(v):
            return hashlib.sha256(v).hexdigest()

        manifest = {
            "archive_version": 1,
            "database": {"archive_name": "database.dump", "sha256": h(data)},
            "objects": [
                {
                    "archive_name": "objects/00000000.bin",
                    "object_key": "fixture",
                    "byte_size": 9,
                    "sha256": h(b"synthetic"),
                }
            ],
        }
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name, v in [
                ("manifest.json", json.dumps(manifest).encode()),
                ("database.dump", data),
                ("objects/00000000.bin", content),
            ]:
                info = tarfile.TarInfo(name)
                info.size = len(v)
                tar.addfile(info, io.BytesIO(v))
        encrypted = Fernet(key).encrypt(buf.getvalue())
        path = tmp_path / "legacy.enc"
        path.write_bytes(encrypted)
        if valid:
            assert backup.inspect_legacy(path, "TEST_LEGACY_KEY")["object_count"] == 1
        else:
            with pytest.raises(ValueError, match="checksum mismatch"):
                backup.inspect_legacy(path, "TEST_LEGACY_KEY")
        assert path.read_bytes() == encrypted and list(tmp_path.iterdir()) == [path]


def test_archive_reader_rejects_wrong_key_and_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("P0_TEST_BACKUP_KEY", key)
    archive_path = tmp_path / "backup.enc"
    tar_path = tmp_path / "payload.tar"
    unsafe = tmp_path / "unsafe.txt"
    unsafe.write_text("unsafe", encoding="utf-8")
    with tarfile.open(tar_path, "w") as archive:
        archive.add(unsafe, arcname="../unsafe.txt")
    archive_path.write_bytes(Fernet(key.encode("ascii")).encrypt(tar_path.read_bytes()))

    with pytest.raises(ValueError, match="unsafe"):
        backup.inspect_legacy(archive_path, key_env="P0_TEST_BACKUP_KEY")
    monkeypatch.setenv("P0_TEST_BACKUP_KEY", Fernet.generate_key().decode("ascii"))
    with pytest.raises(ValueError, match="authentication"):
        backup.inspect_legacy(archive_path, key_env="P0_TEST_BACKUP_KEY")
