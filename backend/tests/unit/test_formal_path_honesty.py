"""Regression: no silent fake / no local:* enqueue / outbox lease reclaim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.events.models import OutboxEvent
from app.events.outbox import OutboxDispatcher
from app.providers.flux import ProviderNotConfiguredError, get_flux_adapter
from app.providers.local_tts import get_local_tts_adapter
from app.shared.enums import OutboxStatus
from sqlalchemy.ext.asyncio import AsyncSession


def test_get_flux_adapter_fail_closed_outside_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.setenv("AGNES_ENABLED", "false")
    from app.config import clear_settings_cache

    clear_settings_cache()
    try:
        with pytest.raises(ProviderNotConfiguredError) as ei:
            get_flux_adapter(allow_live=True, allow_fake=False)
        assert ei.value.code == "PROVIDER_NOT_CONFIGURED"
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        clear_settings_cache()


def test_get_flux_adapter_fake_only_in_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    from app.config import clear_settings_cache

    clear_settings_cache()
    ad = get_flux_adapter()
    assert type(ad).__name__ == "FakeFluxAdapter"


def test_local_tts_adapter_fail_closed_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("TTS_ENABLED", "false")
    from app.config import clear_settings_cache

    clear_settings_cache()
    try:
        with pytest.raises(ProviderNotConfiguredError) as ei:
            get_local_tts_adapter()
        assert ei.value.code == "PROVIDER_NOT_CONFIGURED"
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        clear_settings_cache()


@pytest.mark.asyncio
async def test_enqueue_does_not_return_local_on_redis_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.runtime.scheduler import AgentRunScheduler
    from app.shared.errors import ValidationAppError

    session = MagicMock()
    session.commit = AsyncMock()
    sched = AgentRunScheduler(session)

    async def boom(*_a, **_k):
        raise OSError("redis down")

    monkeypatch.setattr("arq.create_pool", boom)
    with pytest.raises(ValidationAppError) as ei:
        await sched._enqueue_node_run(uuid4())
    assert "QUEUE_UNAVAILABLE" in ei.value.message or "Redis" in ei.value.message
    assert "local:" not in ei.value.message


@pytest.mark.asyncio
async def test_media_node_enqueues_on_heavy_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.config import get_settings
    from app.runtime.scheduler import AgentRunScheduler

    session = MagicMock()
    session.get = AsyncMock(
        side_effect=[
            SimpleNamespace(graph_node_id=uuid4()),
            SimpleNamespace(node_type="keyframe"),
        ]
    )
    redis = MagicMock()
    redis.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id="heavy-job"))
    redis.close = AsyncMock()

    async def create_pool(*_args, **_kwargs):
        return redis

    monkeypatch.setattr("arq.create_pool", create_pool)

    job_id = await AgentRunScheduler(session)._enqueue_node_run(uuid4())

    assert job_id == "heavy-job"
    assert redis.enqueue_job.await_args.kwargs["_queue_name"] == get_settings().arq_heavy_queue_name


@pytest.mark.asyncio
async def test_outbox_reclaim_expired_lease() -> None:
    from app.shared.base import Base
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db_session:
        project_id = uuid4()
        ev = OutboxEvent(
            event_id=uuid4(),
            project_id=project_id,
            topic="node.queued",
            payload={"x": 1},
            schema_version=1,
            status=OutboxStatus.LEASED.value,
            locked_by="dead-worker",
            leased_until=datetime.now(UTC) - timedelta(seconds=60),
            attempt_count=1,
            next_attempt_at=datetime.now(UTC) - timedelta(seconds=120),
        )
        db_session.add(ev)
        await db_session.flush()

        disp = OutboxDispatcher(db_session)
        n = await disp.reclaim_expired_leases()
        assert n >= 1
        await db_session.refresh(ev)
        assert ev.status == OutboxStatus.PENDING.value
        assert ev.locked_by is None

        claimed = await disp.claim_pending(worker_id="w1", limit=5)
        assert any(c.id == ev.id for c in claimed)
        assert claimed[0].status == OutboxStatus.LEASED.value
    await engine.dispose()


def test_stack_script_does_not_force_memory_store() -> None:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    text = (repo / "scripts" / "start_p0_wsl_stack.sh").read_text(encoding="utf-8")
    # Must never assign formal force-memory (=1); comments may mention the forbidden value.
    assert 'export DRAMA_FORCE_MEMORY_STORE="1"' not in text
    assert "DRAMA_FORCE_MEMORY_STORE=1" not in [
        ln.strip() for ln in text.splitlines() if not ln.strip().startswith("#")
    ]
    assert "unset DRAMA_FORCE_MEMORY_STORE" in text or 'DRAMA_FORCE_MEMORY_STORE=""' in text
    api = (repo / "scripts" / "start_api_wsl_stable.sh").read_text(encoding="utf-8")
    assert 'export DRAMA_FORCE_MEMORY_STORE="1"' not in api


def test_insightface_status_reports_backend() -> None:
    from app.consistency.image_embed import insightface_status

    st = insightface_status()
    assert "available" in st
    assert st["embedding_dim"] == 512
    assert st["backend"] in {"insightface+onnx", "hash_placeholder"}


@pytest.mark.asyncio
async def test_resolve_media_bytes_no_stub_outside_test(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import clear_settings_cache
    from app.execution.product_path import _resolve_media_bytes
    from app.shared.errors import ValidationAppError

    monkeypatch.setenv("APP_ENV", "development")
    clear_settings_cache()
    try:
        with pytest.raises(ValidationAppError) as ei:
            await _resolve_media_bytes(
                kind="keyframe", remote="r1", prompt="p", artifact_uri=None
            )
        assert "PROVIDER_MEDIA_MISSING" in ei.value.message or "STUB" in ei.value.message
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        clear_settings_cache()


def test_full_product_script_refuses_force_memory() -> None:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    text = (repo / "scripts" / "run_p0_full_product.py").read_text(encoding="utf-8")
    assert 'setdefault("DRAMA_FORCE_MEMORY_STORE"' not in text
    assert "DRAMA_FORCE_MEMORY_STORE\", \"1\")" not in text
    assert "WorkerRuntime" not in text or "do NOT call WorkerRuntime" in text
    # must not silent FakeFlux for canonical
    assert "canon fallback" not in text
