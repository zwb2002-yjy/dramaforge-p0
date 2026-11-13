"""OS-locked media scratch space, reclaimable only after its owner has exited."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from itertools import islice
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

_KIND = "dramaforge-owned-media-v1"
logger = logging.getLogger(__name__)


def _root() -> Path:
    root = Path(tempfile.gettempdir()) / _KIND
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Media scratch root is not an owned directory")
    return root.resolve()


def _lock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _remove(directory: Path, root: Path) -> None:
    # Both normal release and a recovery sweep check the exact target before
    # recursive removal. Never follow a substituted directory or marker link.
    if directory.is_symlink() or directory.resolve().parent != root:
        raise ValueError("Media scratch target escaped its owned root")
    shutil.rmtree(directory)


class OwnedMediaDirectory:
    def __init__(self, *, operation_id: UUID) -> None:
        self._root = _root()
        self.path = Path(tempfile.mkdtemp(prefix="job-", dir=self._root))
        marker = self.path / "owner.json"
        self._handle = marker.open("x+b")
        try:
            self._handle.write(b" ")
            self._handle.flush()
            _lock(self._handle)
            self._handle.seek(0)
            self._handle.write(
                json.dumps({"kind": _KIND, "operation_id": str(operation_id)}).encode()
            )
            self._handle.truncate()
            self._handle.flush()
        except BaseException:
            self._handle.close()
            _remove(self.path, self._root)
            raise

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *_args: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._handle.closed:
            return
        # Linux permits unlink under the lock; keep it until rmtree completes
        # so a concurrent sweep cannot race the normal owner.
        try:
            if os.name == "nt":
                self._handle.close()
            if self.path.exists():
                _remove(self.path, self._root)
        except (OSError, ValueError):
            # A committed Artifact remains successful. Release ownership so a
            # subsequent startup can retry reclaiming this recognized directory.
            logger.warning("owned_media_cleanup_failed", exc_info=True)
        finally:
            self._handle.close()


def sweep_owned_media(*, limit: int = 1000) -> int:
    """Reclaim dead owners only; an OS lock also fences PID reuse and clock drift."""
    root = _root()
    removed = 0
    for directory in islice(root.iterdir(), limit):
        if (
            not directory.name.startswith("job-")
            or directory.is_symlink()
            or not directory.is_dir()
        ):
            continue
        marker = directory / "owner.json"
        if marker.is_symlink():
            continue
        try:
            with marker.open("r+b") as handle:
                _lock(handle)
                # Bound the marker read; unrecognized files are never collected.
                content = handle.read(1025)
                if len(content) > 1024:
                    continue
                owner = json.loads(content)
                if not isinstance(owner, dict) or owner.get("kind") != _KIND:
                    continue
                UUID(owner["operation_id"])
                if os.name == "nt":
                    handle.close()
                _remove(directory, root)
                removed += 1
        except (OSError, ValueError, KeyError, TypeError):
            # Active owner, incomplete creation, or competing recovery. No
            # process is killed and no unknown or historical files are touched.
            continue
    return removed
