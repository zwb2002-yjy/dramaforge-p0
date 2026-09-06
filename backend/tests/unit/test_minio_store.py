from __future__ import annotations

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
