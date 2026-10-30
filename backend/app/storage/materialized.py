"""Bounded, verified temporary files owned by one media operation."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from anyio import CancelScope


class MediaTransferError(ValueError):
    pass


@dataclass(frozen=True)
class MaterializedFile:
    path: Path
    content_hash: str
    byte_size: int
    content_type: str | None = None


async def materialize_stream(
    chunks: AsyncIterator[bytes],
    *,
    destination: Path,
    max_bytes: int,
    expected_size: int | None = None,
    expected_hash: str | None = None,
) -> MaterializedFile:
    """Create, never overwrite; incomplete files and opened streams are closed."""
    created = False
    try:
        if max_bytes <= 0 or (expected_size is not None and not 0 < expected_size <= max_bytes):
            raise MediaTransferError("Media size is outside the allowed range")
        digest, size = hashlib.sha256(), 0
        with destination.open("xb") as output:
            created = True
            async for chunk in chunks:
                if len(chunk) > 1024 * 1024:
                    raise MediaTransferError("Media stream chunk exceeds the bounded buffer")
                size += len(chunk)
                if size > max_bytes or (expected_size is not None and size > expected_size):
                    raise MediaTransferError("Media stream exceeds the allowed size")
                digest.update(chunk)
                output.write(chunk)
                await asyncio.sleep(0)
        if not size or (expected_size is not None and size != expected_size):
            raise MediaTransferError("Media stream is truncated or empty")
        content_hash = digest.hexdigest()
        if expected_hash is not None and content_hash != expected_hash:
            raise MediaTransferError("Media stream hash mismatch")
        return MaterializedFile(destination, content_hash, size)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        close = getattr(chunks, "aclose", None)
        if close is not None:
            try:
                with CancelScope(shield=True):
                    await asyncio.shield(close())
            except BaseException:
                if created:
                    destination.unlink(missing_ok=True)
                raise
