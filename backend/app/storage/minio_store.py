"""MinIO object storage — single process-wide store for product + tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol, cast

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

    async def delete_bytes(self, *, object_key: str) -> None: ...

    def clear(self) -> None: ...


class _MinioResponse(Protocol):
    def read(self) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class _MinioClient(Protocol):
    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(self, bucket_name: str) -> None: ...

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        length: int,
        content_type: str,
    ) -> object: ...

    def get_object(self, bucket_name: str, object_name: str) -> _MinioResponse: ...

    def remove_object(self, bucket_name: str, object_name: str) -> None: ...


class InMemoryObjectStore:
    """Process-wide test/dev store (shared singleton via get_object_store)."""

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

    async def delete_bytes(self, *, object_key: str) -> None:
        self._objects.pop(object_key, None)

    def clear(self) -> None:
        self._objects.clear()

    def keys(self) -> list[str]:
        return list(self._objects.keys())


class MinioObjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: _MinioClient | None = None

    def clear(self) -> None:
        return None

    def _ensure_client(self) -> _MinioClient:
        if self._client is not None:
            return self._client
        from minio import Minio

        endpoint = self._settings.minio_endpoint.replace("http://", "").replace(
            "https://", ""
        )
        secure = self._settings.minio_endpoint.startswith("https://")
        client = cast(
            _MinioClient,
            Minio(
                endpoint,
                access_key=self._settings.minio_access_key,
                secret_key=self._settings.minio_secret_key,
                secure=secure,
                region=self._settings.minio_region,
            ),
        )
        self._ensure_bucket(client)
        self._client = client
        return client

    def _ensure_bucket(self, client: _MinioClient) -> None:
        bucket = self._settings.minio_bucket
        if client.bucket_exists(bucket):
            return
        try:
            client.make_bucket(bucket)
        except Exception:
            # Another API/Worker process may create the bucket after our check.
            if not client.bucket_exists(bucket):
                raise

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

    async def delete_bytes(self, *, object_key: str) -> None:
        client = self._ensure_client()
        client.remove_object(self._settings.minio_bucket, object_key)


# Process-wide singleton — Worker, export, and tests MUST share this when not using MinIO.
_MEMORY_SINGLETON = InMemoryObjectStore()
_minio_singleton: MinioObjectStore | None = None


def get_object_store(settings: Settings | None = None) -> ObjectStore:
    """Return the process object store.

    - test env or explicit DRAMA_FORCE_MEMORY_STORE=1: shared InMemory singleton
    - formal development/production: MinIO only — never silent memory fallback
    """
    import os

    global _minio_singleton
    cfg = settings or get_settings()
    force_mem = os.environ.get("DRAMA_FORCE_MEMORY_STORE", "").strip() == "1"
    if cfg.app_env == "test" or force_mem:
        return _MEMORY_SINGLETON
    try:
        if _minio_singleton is None:
            _minio_singleton = MinioObjectStore(cfg)
            _minio_singleton._ensure_client()
        return _minio_singleton
    except Exception as exc:
        from app.shared.errors import ValidationAppError

        raise ValidationAppError(
            f"OBJECT_STORE_UNAVAILABLE: MinIO not reachable ({type(exc).__name__}: {exc}). "
            "Start the Docker Compose stack (docker compose up -d). "
            "Memory store is only allowed for APP_ENV=test or DRAMA_FORCE_MEMORY_STORE=1."
        ) from exc


def reset_object_store_for_tests() -> InMemoryObjectStore:
    """Clear shared memory store between tests."""
    _MEMORY_SINGLETON.clear()
    return _MEMORY_SINGLETON
