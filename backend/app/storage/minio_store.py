"""MinIO object storage for Artifacts (binaries only; DB holds key/hash/size)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from app.config import Settings, get_settings


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    content_hash: str
    byte_size: int
    mime_type: str


class ObjectStore(Protocol):
    async def put_bytes(
        self, *, object_key: str, data: bytes, mime_type: str
    ) -> StoredObject: ...

    async def get_bytes(self, *, object_key: str) -> bytes: ...


class InMemoryObjectStore:
    """Test double when MinIO is unavailable."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put_bytes(
        self, *, object_key: str, data: bytes, mime_type: str
    ) -> StoredObject:
        self._objects[object_key] = data
        return StoredObject(
            object_key=object_key,
            content_hash=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            mime_type=mime_type,
        )

    async def get_bytes(self, *, object_key: str) -> bytes:
        if object_key not in self._objects:
            raise KeyError(object_key)
        return self._objects[object_key]


class MinioObjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = None

    def _ensure_client(self):  # type: ignore[no-untyped-def]
        if self._client is not None:
            return self._client
        from minio import Minio  # type: ignore[import-untyped]

        endpoint = self._settings.minio_endpoint.replace("http://", "").replace(
            "https://", ""
        )
        secure = self._settings.minio_endpoint.startswith("https://")
        self._client = Minio(
            endpoint,
            access_key=self._settings.minio_access_key,
            secret_key=self._settings.minio_secret_key,
            secure=secure,
            region=self._settings.minio_region,
        )
        bucket = self._settings.minio_bucket
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)
        return self._client

    async def put_bytes(
        self, *, object_key: str, data: bytes, mime_type: str
    ) -> StoredObject:
        client = self._ensure_client()
        content_hash = hashlib.sha256(data).hexdigest()
        client.put_object(
            self._settings.minio_bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=mime_type,
        )
        return StoredObject(
            object_key=object_key,
            content_hash=content_hash,
            byte_size=len(data),
            mime_type=mime_type,
        )

    async def get_bytes(self, *, object_key: str) -> bytes:
        client = self._ensure_client()
        response = client.get_object(self._settings.minio_bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


_memory = InMemoryObjectStore()


def get_object_store(settings: Settings | None = None) -> ObjectStore:
    """Prefer MinIO; fall back to memory if client import/connect fails in unit tests."""
    cfg = settings or get_settings()
    if cfg.app_env == "test":
        return _memory
    try:
        store = MinioObjectStore(cfg)
        store._ensure_client()
        return store
    except Exception:
        return _memory
