from __future__ import annotations

import asyncio
import hashlib
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.config import get_settings
from app.storage.minio_store import MinioObjectStore
from fastapi.responses import StreamingResponse


async def test_file_upload_reads_a_handle_and_closes_it_after_failure(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"bounded-stream" * 10000)
    store = MinioObjectStore(get_settings())
    client = Mock()
    store._client = client
    readers = []

    def upload(bucket, key, data, *, length, content_type, num_parallel_uploads):
        assert num_parallel_uploads == 1
        assert bucket and key == "video.mp4" and content_type == "video/mp4"
        assert length == source.stat().st_size
        assert not isinstance(data, bytes)
        readers.append(data)
        digest = hashlib.sha256()
        while chunk := data.read(65536):
            digest.update(chunk)
        assert digest.hexdigest() == hashlib.sha256(source.read_bytes()).hexdigest()

    client.put_object.side_effect = upload
    stored = await store.put_file(object_key="video.mp4", path=source, mime_type="video/mp4")
    assert stored.byte_size == source.stat().st_size
    assert readers[0].closed
    client.put_object.side_effect = OSError("disconnected")
    with pytest.raises(OSError, match="disconnected"):
        await store.put_file(object_key="video.mp4", path=source, mime_type="video/mp4")
    assert client.put_object.call_args.args[2].closed
    assert source.exists(), "ObjectStore never deletes the caller's file"


async def test_cancelled_file_upload_waits_until_sdk_releases_the_file(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"owned")
    store = MinioObjectStore(get_settings())
    entered, release = Event(), Event()
    client = Mock()
    store._client = client
    readers = []

    def upload(*args, **kwargs):
        readers.append(args[2])
        entered.set()
        assert release.wait(5)
        assert args[2].read() == b"owned"

    client.put_object.side_effect = upload
    task = asyncio.create_task(store.put_file(object_key="v", path=source, mime_type="video/mp4"))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert readers[0].closed


class _BucketClient:
    def __init__(self, exists_results: list[bool]) -> None:
        self.exists_results = iter(exists_results)
        self.make_calls = 0

    def bucket_exists(self, bucket_name: str) -> bool:
        assert bucket_name
        return next(self.exists_results)

    def make_bucket(self, bucket_name: str) -> None:
        assert bucket_name
        self.make_calls += 1
        raise RuntimeError("concurrent bucket creation")


def test_ensure_bucket_accepts_concurrent_creation() -> None:
    store = MinioObjectStore(get_settings())
    client = _BucketClient([False, True])

    store._ensure_bucket(client)  # noqa: SLF001

    assert client.make_calls == 1


def test_ensure_bucket_preserves_failure_when_bucket_is_still_missing() -> None:
    store = MinioObjectStore(get_settings())
    client = _BucketClient([False, False])

    with pytest.raises(RuntimeError, match="concurrent bucket creation"):
        store._ensure_bucket(client)  # noqa: SLF001

    assert client.make_calls == 1


async def test_minio_size_check_is_metadata_only_and_range_stays_native() -> None:
    store = MinioObjectStore(get_settings())
    response = Mock()
    response.read.return_value = b"234"
    client = Mock()
    client.stat_object.return_value = SimpleNamespace(size=10)
    client.get_object.return_value = response
    store._client = client

    assert await store.get_size(object_key="media.mp4") == 10
    client.get_object.assert_not_called()
    assert await store.get_range(object_key="media.mp4", offset=2, length=3) == b"234"
    client.stat_object.assert_called_once_with(store._settings.minio_bucket, "media.mp4")
    client.get_object.assert_called_once_with(
        store._settings.minio_bucket, "media.mp4", offset=2, length=3
    )
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


async def test_minio_stream_uses_one_get_bounded_reads_and_closes_on_early_exit():
    store = MinioObjectStore(get_settings())
    response = Mock()
    response.read.side_effect = [b"x" * 65536, b"remaining"]
    client = Mock()
    client.get_object.return_value = response
    store._client = client
    stream = store.iter_bytes(object_key="large.mp4", length=1024 * 1024)
    assert len(await anext(stream)) == 65536
    response.read.assert_called_once_with(65536)
    await stream.aclose()
    client.get_object.assert_called_once()
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


@pytest.mark.parametrize("blocked_phase", ["open", "read"])
async def test_minio_stream_disconnect_releases_inflight_response(blocked_phase):
    store = MinioObjectStore(get_settings())
    started, release = Event(), Event()
    io_finished = Event()
    closed_before_io_finished = []
    response = Mock()

    def block():
        started.set()
        assert release.wait(2), "test did not release storage IO"
        io_finished.set()

    def open_response(*args, **kwargs):
        if blocked_phase == "open":
            block()
        return response

    def read(_size):
        if blocked_phase == "read":
            block()
        return b""

    response.read.side_effect = read
    response.close.side_effect = lambda: closed_before_io_finished.append(not io_finished.is_set())
    client = Mock()
    client.get_object.side_effect = open_response
    store._client = client
    stream = StreamingResponse(store.iter_bytes(object_key="disconnect.mp4"))

    async def receive():
        while not started.is_set():
            await asyncio.sleep(0.001)
        return {"type": "http.disconnect"}

    async def send(_message):
        pass

    async def finish_io():
        while not started.is_set():
            await asyncio.sleep(0.001)
        await asyncio.sleep(0.02)
        release.set()

    finishing = asyncio.create_task(finish_io())
    try:
        await asyncio.wait_for(
            stream({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send),
            timeout=2,
        )
        await finishing
        await asyncio.to_thread(lambda: None)
        response.close.assert_called_once()
        response.release_conn.assert_called_once()
        assert closed_before_io_finished == [False]
    finally:
        release.set()
        await finishing


@pytest.mark.parametrize("operation", ["get_size", "get_bytes", "get_range"])
async def test_minio_missing_object_has_the_same_error_as_memory(operation) -> None:
    from minio.error import S3Error

    store = MinioObjectStore(get_settings())
    client = Mock()
    missing = S3Error(
        response=None,
        code="NoSuchKey",
        message="missing",
        resource="media.mp4",
        request_id="request",
        host_id="host",
    )
    client.stat_object.side_effect = missing
    client.get_object.side_effect = missing
    store._client = client
    kwargs = {"object_key": "media.mp4"}
    if operation == "get_range":
        kwargs.update(offset=2, length=3)
    with pytest.raises(KeyError):
        await getattr(store, operation)(**kwargs)


async def test_minio_out_of_range_error_is_mapped_for_api_validation() -> None:
    from minio.error import S3Error

    store = MinioObjectStore(get_settings())
    client = Mock()
    client.get_object.side_effect = S3Error(
        response=None,
        code="InvalidRange",
        message="outside object",
        resource="media.mp4",
        request_id="request",
        host_id="host",
    )
    store._client = client
    with pytest.raises(IndexError):
        await store.get_range(object_key="media.mp4", offset=20, length=3)
