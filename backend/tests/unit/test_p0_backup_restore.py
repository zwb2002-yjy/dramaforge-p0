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


def test_restore_must_use_distinct_database_and_bucket() -> None:
    with pytest.raises(ValueError, match="database"):
        backup._assert_isolated_target(
            "postgresql+asyncpg://user:pass@db/dramaforge",
            "postgresql+asyncpg://user:pass@db/dramaforge",
            "dramaforge",
            "dramaforge-restore",
        )
    with pytest.raises(ValueError, match="bucket"):
        backup._assert_isolated_target(
            "postgresql+asyncpg://user:pass@db/source",
            "postgresql+asyncpg://user:pass@db/restore",
            "dramaforge",
            "dramaforge",
        )


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
        backup._read_archive(
            archive_path,
            key_env="P0_TEST_BACKUP_KEY",
            work=tmp_path / "work",
        )
    monkeypatch.setenv("P0_TEST_BACKUP_KEY", Fernet.generate_key().decode("ascii"))
    with pytest.raises(ValueError, match="authentication"):
        backup._read_archive(
            archive_path,
            key_env="P0_TEST_BACKUP_KEY",
            work=tmp_path / "other-work",
        )
