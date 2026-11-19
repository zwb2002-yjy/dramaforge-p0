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
    def iter_bytes(self, *, object_key: str) -> AsyncIterator[bytes]: ...


def staging_free_bytes(path: Path) -> int:
    """Free bytes on the filesystem that will hold the staging area."""
    return int(shutil.disk_usage(path).free)


def _safe_target(root: Path, *, bucket: str, key: str) -> Path:
    """Keep staged paths inside the staging root, even for hostile keys."""
    if not bucket.strip() or "/" in bucket or "\\" in bucket or bucket in {".", ".."}:
        raise BackupManifestError("BACKUP_OBJECT_INVALID", f"unsafe bucket name: {bucket!r}")
    relative = Path(key)
    if relative.is_absolute() or ".." in relative.parts:
        raise BackupManifestError("BACKUP_OBJECT_INVALID", f"unsafe object key: {key!r}")
    target = (root / "objects" / bucket / relative).resolve()
    if root.resolve() not in target.parents:
        raise BackupManifestError("BACKUP_OBJECT_INVALID", f"object escapes staging: {key!r}")
    return target


async def stage_object(
    store: StreamableStore,
    *,
    bucket: str,
    key: str,
    staging_dir: Path,
    max_object_bytes: int | None = None,
) -> ObjectEntry:
    """Stream one object to disk, returning its measured size and hash."""
    target = _safe_target(staging_dir, bucket=bucket, key=key)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as handle:
            async for chunk in store.iter_bytes(object_key=key):
                size += len(chunk)
                if max_object_bytes is not None and size > max_object_bytes:
                    raise BackupManifestError(
                        "BACKUP_OBJECT_TOO_LARGE",
                        f"{bucket}/{key} exceeds {max_object_bytes} bytes while staging",
                    )
                digest.update(chunk)
                handle.write(chunk)
    except BaseException:
        # Never leave a truncated object behind: it would look restorable.
        target.unlink(missing_ok=True)
        raise
    if size == 0:
        target.unlink(missing_ok=True)
        raise BackupManifestError("BACKUP_OBJECT_INVALID", f"{bucket}/{key} is empty")
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
        )
        total += entry.size
        if max_total_bytes is not None and total > max_total_bytes:
            raise BackupManifestError(
                "BACKUP_CAPACITY_INSUFFICIENT",
                f"staged {total} bytes for {bucket}, cap {max_total_bytes}",
            )
        entries.append(entry)
    return entries


__all__ = ["CHUNK_BYTES", "StreamableStore", "stage_object", "stage_objects", "staging_free_bytes"]
