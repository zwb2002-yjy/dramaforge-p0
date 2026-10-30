"""Size/hash/cancellation boundaries for one owned temporary media file."""

import asyncio
import hashlib

import pytest
from app.storage.materialized import MediaTransferError, materialize_stream


@pytest.mark.parametrize("failure", [None, "short", "long", "hash", "disconnect"])
async def test_materialization_validates_the_actual_stream_and_closes_it(tmp_path, failure):
    closed, consumed = [], []
    data = b"a" * 65536 + b"b" * 31

    async def stream():
        try:
            for chunk in (data[:65536], data[65536:]):
                consumed.append(len(chunk))
                yield chunk
            if failure == "disconnect":
                raise OSError("synthetic response loss")
        finally:
            closed.append(True)

    target = tmp_path / "media"
    size = len(data) + (1 if failure == "short" else -1 if failure == "long" else 0)
    request = materialize_stream(
        stream(),
        destination=target,
        max_bytes=len(data) + 1,
        expected_size=size,
        expected_hash="0" * 64 if failure == "hash" else hashlib.sha256(data).hexdigest(),
    )
    if failure:
        with pytest.raises((MediaTransferError, OSError)):
            await request
        assert not target.exists()
    else:
        result = await request
        assert result.path == target and result.byte_size == len(data)
        assert result.content_hash == hashlib.sha256(data).hexdigest()
        assert target.read_bytes() == data
    assert closed == [True]


async def test_unknown_length_limit_stops_before_consuming_the_whole_stream(tmp_path):
    reads = []

    async def chunks():
        for _ in range(100):
            reads.append(1)
            yield b"a" * 1024

    target = tmp_path / "too-big"
    with pytest.raises(MediaTransferError, match="size"):
        await materialize_stream(chunks(), destination=target, max_bytes=2048)
    assert len(reads) == 3 and not target.exists()


async def test_materialization_cancellation_removes_only_its_created_file(tmp_path):
    prior = tmp_path / "prior"
    prior.write_bytes(b"retained")
    reached, closed = asyncio.Event(), asyncio.Event()

    async def chunks():
        try:
            yield b"first"
            reached.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    target = tmp_path / "partial"
    task = asyncio.create_task(materialize_stream(chunks(), destination=target, max_bytes=100))
    await reached.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and not target.exists() and prior.read_bytes() == b"retained"

    with pytest.raises(FileExistsError):
        await materialize_stream(chunks(), destination=prior, max_bytes=100)
    assert prior.read_bytes() == b"retained"
