from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.config import get_settings
from app.storage.minio_store import MinioObjectStore


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
