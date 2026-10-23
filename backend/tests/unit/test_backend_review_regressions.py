"""Regression tests for backend-review hardening of blocking IO and Director admission."""

from __future__ import annotations

import threading
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.production.application import batch_production as batch
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
@pytest.mark.parametrize(
    "entrypoint",
    ["accept", "accept_existing_new_turn", "accept_existing_detached_turn"],
)
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


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return self._rows


@pytest.mark.asyncio
async def test_batch_preview_fingerprint_binds_compiler_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shot_id, scene_id, project_id = uuid4(), uuid4(), uuid4()
    shot = SimpleNamespace(
        id=shot_id,
        project_id=project_id,
        scene_id=scene_id,
        shot_number=1,
        sort_order=1,
        version=1,
        formal_keyframe_artifact_id=None,
        image_prompt="single test image",
        visual_description="test",
    )
    project = SimpleNamespace(id=project_id)

    async def run_preview(proof: str | None) -> tuple[batch.BatchProductionPreviewRead, object]:
        session = AsyncMock()
        session.execute.side_effect = [_Rows([shot]), _Rows([])]
        plan = SimpleNamespace(
            plan_fingerprint="1" * 64,
            resolved_model=SimpleNamespace(resolved_model_id="model"),
        )
        service = SimpleNamespace(
            saved_shot_references=AsyncMock(return_value=[]),
            build_plan=AsyncMock(return_value=plan),
            preview_compiler_contract=AsyncMock(
                return_value=(
                    SimpleNamespace(readiness="contract_validated", wire_fingerprint=proof)
                    if proof is not None
                    else None
                )
            ),
        )
        monkeypatch.setattr(batch, "WorkbenchExecutionService", lambda *_args, **_kw: service)
        return await batch._prepare(
            session, project=project, user_id=uuid4(), stage="image_keyframe", scene_id=None,
        )

    first, ready = await run_preview("a" * 64)
    second, _ = await run_preview("b" * 64)
    blocked, not_ready = await run_preview(None)
    assert first.ready_count == second.ready_count == 1
    assert first.fingerprint != second.fingerprint
    assert ready[shot_id][2] == "a" * 64
    assert blocked.ready_count == 0 and not not_ready
    assert blocked.items[0].reason == "COMPILER_WIRE_CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", [True, False])
async def test_batch_authorization_replay_is_safe(
    monkeypatch: pytest.MonkeyPatch, same_key: bool,
) -> None:
    project_id, actor_id, run_id = uuid4(), uuid4(), uuid4()
    preview_hash = "a" * 64
    project = SimpleNamespace(id=project_id)
    actor = SimpleNamespace(id=actor_id)
    profile_lock = AsyncMock()
    monkeypatch.setattr(
        batch,
        "ProjectService",
        lambda _session: SimpleNamespace(
            get_project_for_owner=AsyncMock(return_value=project),
        ),
    )
    monkeypatch.setattr(
        batch,
        "WorkbenchExecutionService",
        lambda *_args, **_kw: SimpleNamespace(lock_command_scope=profile_lock),
    )
    preview = batch.BatchProductionPreviewRead(
        project_id=project_id, scene_id=None, stage="image_keyframe",
        fingerprint=preview_hash, ready_count=1, skipped_count=0, blocked_count=0, items=[],
    )
    prepare = AsyncMock(return_value=(preview, {uuid4(): (None, None, "b" * 64)}))
    monkeypatch.setattr(batch, "_prepare", prepare)
    run = SimpleNamespace(
        id=run_id,
        status="queued",
        input_snapshot={
            "paid_authorization": {
                "batch_key": "original",
                "stage": "image_keyframe",
                "preview_fingerprint": preview_hash,
                "authorized_by": str(actor_id),
                "authorized_call_count": 1,
                "call_index": 1,
            },
        },
    )
    session = AsyncMock()
    session.scalars.side_effect = (
        [_Rows([run])] if same_key else [_Rows([]), _Rows([run])]
    )
    body = batch.BatchProductionDispatchBody(
        stage="image_keyframe", preview_fingerprint=preview_hash,
        batch_key="original" if same_key else "replacement",
        owner_authorized=True, max_provider_calls=1,
    )
    if same_key:
        receipt = await batch.dispatch_batch_production(project_id, body, actor, session)
        assert receipt.node_run_ids == [run_id]
        assert receipt.accepted_count == 1
        prepare.assert_not_awaited()
    else:
        with pytest.raises(ConflictError) as exc:
            await batch.dispatch_batch_production(project_id, body, actor, session)
        assert exc.value.details["code"] == "BATCH_PREVIEW_ALREADY_AUTHORIZED"
        prepare.assert_awaited_once()
    profile_lock.assert_awaited_once()
    session.commit.assert_not_awaited()
