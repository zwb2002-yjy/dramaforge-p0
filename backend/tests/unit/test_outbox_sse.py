"""Outbox dead-letter/replay and SSE Last-Event-ID tests on shipped code."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access import models as _a  # noqa: F401
from app.events import models as _e  # noqa: F401
from app.events.models import OutboxEvent
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.events.sse import SseHub, format_sse
from app.execution import models as _x  # noqa: F401
from app.production import models as _p  # noqa: F401
from app.shared.base import Base
from app.shared.enums import OutboxStatus
from app.shared.observability import metrics_payload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def engine_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_outbox_publish_and_dead_letter_then_idempotent_replay_across_instances(
    engine_factory,
) -> None:
    _engine, factory = engine_factory
    publisher = StreamPublisher()
    async with factory() as session:
        dispatcher = OutboxDispatcher(session, publisher, max_attempts=2)
        event = OutboxEvent(
            event_id=uuid4(),
            topic="node.completed",
            schema_version=1,
            payload={"shot": "1"},
            status=OutboxStatus.PENDING.value,
            attempt_count=0,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        claimed = await dispatcher.claim_pending(worker_id="w1", limit=5)
        assert len(claimed) == 1
        dl = await dispatcher.fail_leased(claimed[0], error="stream down")
        assert dl is None
        await session.commit()

        claimed2 = await dispatcher.claim_pending(worker_id="w1", limit=5)
        assert len(claimed2) == 1
        dl = await dispatcher.fail_leased(claimed2[0], error="stream still down")
        assert dl is not None
        await session.commit()
        dl_id = dl.id

        replayed = await dispatcher.human_replay_dead_letter(dl_id, operator="ops")
        await session.commit()
        assert replayed.status == OutboxStatus.PUBLISHED.value
        assert len(publisher.messages) == 1

    # Fresh dispatcher instances must not double-publish (durable published singleflight)
    async with factory() as session2:
        d2 = OutboxDispatcher(session2, publisher, max_attempts=2)
        again = await d2.human_replay_dead_letter(dl_id, operator="ops2")
        await session2.commit()
        assert again.status == OutboxStatus.PUBLISHED.value
    async with factory() as session3:
        d3 = OutboxDispatcher(session3, publisher, max_attempts=2)
        third = await d3.human_replay_dead_letter(dl_id, operator="ops3")
        await session3.commit()
        assert third.status == OutboxStatus.PUBLISHED.value

    assert len(publisher.messages) == 1
    metrics = metrics_payload().decode("utf-8")
    assert "dramaforge_outbox_dead_letter_total" in metrics
    assert "dramaforge_outbox_published_total" in metrics
    assert "dramaforge_outbox_replay_total" in metrics


@pytest.mark.asyncio
async def test_sse_last_event_id_resume() -> None:
    hub = SseHub(capacity=100)
    e1 = hub.publish(event="node.progress", data={"n": 1})
    e2 = hub.publish(event="node.completed", data={"n": 2})
    resumed = hub.since(e1.id)
    assert len(resumed) == 1
    assert resumed[0].id == e2.id
    text = format_sse(e2)
    assert f"id: {e2.id}" in text
    gen = hub.stream(last_event_id=e1.id)
    first = await gen.__anext__()
    assert first.id == e2.id
    assert "dramaforge_sse_reconnect_total" in metrics_payload().decode("utf-8")
