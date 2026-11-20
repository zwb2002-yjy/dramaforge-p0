"""Object staging streams and hashes without holding an object in memory (I10-01)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from app.maintenance.backup_manifest import BackupManifestError
from app.maintenance.object_staging import stage_object, stage_objects, staging_free_bytes


class MemoryStore:
    """Minimal streaming store: the interface the staging code actually needs."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.reads: list[str] = []

    async def get_size(self, *, object_key: str) -> int:
        return len(self.objects[object_key])

    async def iter_bytes(self, *, object_key: str):
        self.reads.append(object_key)
        data = self.objects[object_key]
        for offset in range(0, len(data), 7):  # deliberately tiny chunks
            yield data[offset : offset + 7]


@pytest.mark.asyncio
async def test_objects_are_streamed_and_hashed(tmp_path: Path) -> None:
    payload = b"media-bytes-" * 500
    store = MemoryStore({"projects/p1/a.mp4": payload})
    entries = await stage_objects(
        store, bucket="media", keys=["projects/p1/a.mp4"], staging_dir=tmp_path
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.size == len(payload)
    assert entry.sha256 == hashlib.sha256(payload).hexdigest()
    staged = tmp_path / "objects" / "media" / "projects" / "p1" / "a.mp4"
    assert staged.read_bytes() == payload
    assert store.reads == ["projects/p1/a.mp4"]


@pytest.mark.asyncio
async def test_oversized_object_is_refused_without_leaving_a_partial_file(
    tmp_path: Path,
) -> None:
    store = MemoryStore({"projects/p1/big.mp4": b"x" * 5000})
    with pytest.raises(BackupManifestError) as too_large:
        await stage_object(
            store,
            bucket="media",
            key="projects/p1/big.mp4",
            staging_dir=tmp_path,
            max_object_bytes=1000,
        )
    assert too_large.value.code == "BACKUP_OBJECT_TOO_LARGE"
    target = tmp_path / "objects" / "media" / "projects" / "p1" / "big.mp4"
    assert not target.exists()


@pytest.mark.asyncio
async def test_empty_object_and_unsafe_key_are_refused(tmp_path: Path) -> None:
    empty = MemoryStore({"k": b""})
    with pytest.raises(BackupManifestError) as blank:
        await stage_object(empty, bucket="media", key="k", staging_dir=tmp_path)
    assert blank.value.code == "BACKUP_OBJECT_INVALID"

    store = MemoryStore({"../escape.mp4": b"abc"})
    with pytest.raises(BackupManifestError) as escape:
        await stage_object(store, bucket="media", key="../escape.mp4", staging_dir=tmp_path)
    assert escape.value.code == "BACKUP_OBJECT_INVALID"

    with pytest.raises(BackupManifestError) as bad_bucket:
        await stage_object(store, bucket="../etc", key="x", staging_dir=tmp_path)
    assert bad_bucket.value.code == "BACKUP_OBJECT_INVALID"


@pytest.mark.asyncio
async def test_total_cap_and_deterministic_order(tmp_path: Path) -> None:
    store = MemoryStore({"b": b"12345", "a": b"12345"})
    entries = await stage_objects(store, bucket="media", keys=["b", "a", "a"], staging_dir=tmp_path)
    # Duplicate keys collapse and the order does not depend on input order.
    assert [entry.key for entry in entries] == ["a", "b"]

    with pytest.raises(BackupManifestError) as capped:
        await stage_objects(
            store,
            bucket="media",
            keys=["a", "b"],
            staging_dir=tmp_path / "second",
            max_total_bytes=6,
        )
    assert capped.value.code == "BACKUP_CAPACITY_INSUFFICIENT"
    assert not (tmp_path / "second" / "objects" / "media" / "b").exists()


async def test_incomplete_stream_and_retry_do_not_replace_a_complete_object(tmp_path: Path):
    class ShortStore(MemoryStore):
        async def get_size(self, *, object_key: str) -> int:
            return await super().get_size(object_key=object_key) + 1

    with pytest.raises(BackupManifestError, match="BACKUP_OBJECT_SIZE_MISMATCH"):
        await stage_object(ShortStore({"a": b"x"}), bucket="media", key="a", staging_dir=tmp_path)
    target = tmp_path / "objects" / "media" / "a"
    assert not target.exists()
    await stage_object(
        MemoryStore({"a": b"original"}), bucket="media", key="a", staging_dir=tmp_path
    )
    with pytest.raises(FileExistsError):
        await stage_object(
            MemoryStore({"a": b"replacement"}), bucket="media", key="a", staging_dir=tmp_path
        )
    assert target.read_bytes() == b"original"


def test_staging_free_bytes_reports_the_filesystem(tmp_path: Path) -> None:
    assert staging_free_bytes(tmp_path) > 0
