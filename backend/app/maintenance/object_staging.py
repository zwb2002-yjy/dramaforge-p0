"""Stage object bytes for a backup without loading them whole (I10-01).

The bundle needs every object's real size and hash, and the contract forbids
reading a whole object into memory to get them. Staging therefore streams each
object into the bounded staging area in chunks, hashing as it writes, and aborts
on an oversized object or a short read instead of keeping a partial file.

Nothing here talks to restic; it produces the ``ObjectEntry`` list the manifest
records and the files the snapshot then captures.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Protocol

from app.maintenance.backup_manifest import BackupManifestError, ObjectEntry

CHUNK_BYTES = 64 * 1024


class StreamableStore(Protocol):
    async def get_size(self, *, object_key: str) -> int: ...

    def iter_bytes(self, *, object_key: str) -> AsyncIterator[bytes]: ...


def staging_free_bytes(path: Path) -> int:
    """Free bytes on the filesystem that will hold the staging area."""
    return int(shutil.disk_usage(path).free)


def _safe_target(root: Path, *, bucket: str, key: str) -> Path:
    """Keep staged paths inside the staging root, even for hostile keys."""
    if not bucket.strip() or "/" in bucket or "\\" in bucket or bucket in {".", ".."}:
        raise BackupManifestError("BACKUP_OBJECT_INVALID", f"unsafe bucket name: {bucket!r}")
    components = key.split("/")
    if "\\" in key or any(part in {"", ".", ".."} for part in components):
        raise BackupManifestError("BACKUP_OBJECT_INVALID", "object key has no unique staging path")
    base = root.resolve() / "objects" / bucket
    target = base.joinpath(*components)
    if target.resolve() != target or base not in target.parents:
        raise BackupManifestError("BACKUP_OBJECT_INVALID", f"unsafe staging path: {key!r}")
    return target


async def stage_object(
    store: StreamableStore,
    *,
    bucket: str,
    key: str,
    staging_dir: Path,
    max_object_bytes: int | None = None,
    remaining_bytes: int | None = None,
) -> ObjectEntry:
    """Stream one object to disk, returning its measured size and hash."""
    target = _safe_target(staging_dir, bucket=bucket, key=key)
    expected = await store.get_size(object_key=key)
    if expected <= 0:
        raise BackupManifestError("BACKUP_OBJECT_INVALID", f"{bucket}/{key} is empty or missing")
    if max_object_bytes is not None and expected > max_object_bytes:
        raise BackupManifestError("BACKUP_OBJECT_TOO_LARGE", f"{bucket}/{key} exceeds object limit")
    if remaining_bytes is not None and expected > remaining_bytes:
        raise BackupManifestError(
            "BACKUP_CAPACITY_INSUFFICIENT", f"{bucket}/{key} exceeds remaining capacity"
        )
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    # Opening exclusively keeps a previous complete capture intact on retry.
    handle = target.open("xb")
    try:
        with handle:
            async for chunk in store.iter_bytes(object_key=key):
                size += len(chunk)
                if size > expected:
                    raise BackupManifestError(
                        "BACKUP_OBJECT_SIZE_MISMATCH", f"{bucket}/{key} grew during capture"
                    )
                digest.update(chunk)
                handle.write(chunk)
        if size != expected:
            raise BackupManifestError(
                "BACKUP_OBJECT_SIZE_MISMATCH", f"{bucket}/{key} was truncated during capture"
            )
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return ObjectEntry(bucket=bucket, key=key, size=size, sha256=digest.hexdigest())


async def stage_objects(
    store: StreamableStore,
    *,
    bucket: str,
    keys: Iterable[str],
    staging_dir: Path,
    max_object_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> list[ObjectEntry]:
    """Stage a bucket's objects deterministically; refuse to overshoot the cap."""
    entries: list[ObjectEntry] = []
    total = 0
    for key in sorted(set(keys)):
        entry = await stage_object(
            store,
            bucket=bucket,
            key=key,
            staging_dir=staging_dir,
            max_object_bytes=max_object_bytes,
            remaining_bytes=None if max_total_bytes is None else max_total_bytes - total,
        )
        total += entry.size
        entries.append(entry)
    return entries


__all__ = ["CHUNK_BYTES", "StreamableStore", "stage_object", "stage_objects", "staging_free_bytes"]
