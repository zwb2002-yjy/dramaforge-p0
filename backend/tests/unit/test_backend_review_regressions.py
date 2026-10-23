"""Regression tests for backend-review hardening of blocking IO and Director admission."""

from __future__ import annotations

import asyncio
import threading
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.director.runtime.capabilities import DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED
from app.director.runtime.start import DirectorRuntimeStartService
from app.shared.errors import ConflictError
from app.storage.minio_store import MinioObjectStore


class _Response:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self.data

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _StorageClient:
    def __init__(self) -> None:
        self.threads: list[int] = []
        self.objects: dict[str, bytes] = {}
        self.response: _Response | None = None

    def put_object(
        self, bucket_name: str, object_name: str, data: BytesIO, length: int,
        content_type: str,
    ) -> None:
        self.threads.append(threading.get_ident())
        self.objects[object_name] = data.read()

    def get_object(self, bucket_name: str, object_name: str) -> _Response:
        self.threads.append(threading.get_ident())
        self.response = _Response(self.objects[object_name])
        return self.response

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.threads.append(threading.get_ident())
        self.objects.pop(object_name)


def _settings(**overrides: object) -> Settings:
    options: dict[str, object] = {
        "app_env": "test",
        "session_secret": "test-session-secret-32chars-min",
        "byok_fernet_key": "test-byok-fernet-key-replace==",
    }
    options.update(overrides)
    return Settings(**options)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_minio_operations_run_off_event_loop() -> None:
    store = MinioObjectStore(_settings())
    client = _StorageClient()
    store._client = client  # type: ignore[assignment]
    loop_thread = threading.get_ident()
    obj = await store.put_bytes(object_key="test", data=b"hello", mime_type="text/plain")
    assert obj.byte_size == 5
    assert await store.get_bytes(object_key="test") == b"hello"
    await store.delete_bytes(object_key="test")
    assert client.objects == {}
    assert client.response is not None and client.response.closed and client.response.released
    assert len(client.threads) == 3
    assert all(worker_thread != loop_thread for worker_thread in client.threads)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["accept", "accept_existing_new_turn", "accept_existing_detached_turn"])
async def test_director_start_fails_before_db_write_without_checkpoint(entrypoint: str) -> None:
    session = AsyncMock()
    service = DirectorRuntimeStartService(
        session,
        settings=_settings(director_checkpoint_database_url=""),
    )
    if entrypoint == "accept":
        call = service.accept(
            project=None, actor=None, proposal_id=uuid4(),
            authorization_ref=None, request_key="test", max_steps=4,
        )
    elif entrypoint == "accept_existing_new_turn":
        call = service.accept_existing_new_turn(
            project=None, actor=None, turn=None, proposal_id=uuid4(), created=True,
        )
    else:
        call = service.accept_existing_detached_turn(
            project=None, actor=None, turn=None, created=True,
        )
    with pytest.raises(ConflictError) as exc:
        await call
    assert exc.value.details["code"] == DIRECTOR_BLOCKER_CHECKPOINT_NOT_CONFIGURED
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()
