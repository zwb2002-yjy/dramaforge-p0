"""Outbox dead-letter/replay and SSE Last-Event-ID tests on shipped code."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access import models as _a  # noqa: F401
from app.events import models as _e  # noqa: F401
from app.events.models import OutboxEvent
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.events.sse import SseHub, format_sse
from app.production import models as _p  # noqa: F401
from app.shared.base import Base
from app.shared.enums import OutboxStatus
from app.shared.observability import metrics_payload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_outbox_publish_and_dead_letter_then_idempotent_replay(
    session: AsyncSession,
) -> None:
    publisher = StreamPublisher()
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
    assert claimed[0].status == OutboxStatus.LEASED.value

    dl = await dispatcher.fail_leased(claimed[0], error="stream down")
    assert dl is None  # first failure requeues
    await session.commit()

    claimed2 = await dispatcher.claim_pending(worker_id="w1", limit=5)
    assert claimed2[0].attempt_count == 2
    dl = await dispatcher.fail_leased(claimed2[0], error="stream still down")
    assert dl is not None
    await session.commit()
    assert claimed2[0].status == OutboxStatus.DEAD_LETTER.value

    replayed = await dispatcher.human_replay_dead_letter(dl.id, operator="ops")
    await session.commit()
    assert replayed.status == OutboxStatus.PUBLISHED.value
    assert len(publisher.messages) == 1

    # Second replay is idempotent — no second publish
    again = await dispatcher.human_replay_dead_letter(dl.id, operator="ops")
    await session.commit()
    assert again.event_id == replayed.event_id
    assert len(publisher.messages) == 1

    n = await dispatcher.pending_count()
    assert n == 0
    metrics = metrics_payload().decode("utf-8")
    assert "dramaforge_outbox_dead_letter_total" in metrics
    assert "dramaforge_outbox_published_total" in metrics
    assert "dramaforge_outbox_replay_total" in metrics


@pytest.mark.asyncio
async def test_sse_last_event_id_resume() -> None:
    hub = SseHub(capacity=100)
    e1 = hub.publish(event="node.progress", data={"n": 1})
    e2 = hub.publish(event="node.completed", data={"n": 2})
    assert e1.id != e2.id
    resumed = hub.since(e1.id)
    assert len(resumed) == 1
    assert resumed[0].id == e2.id
    full = hub.since(None)
    assert len(full) == 2
    text = format_sse(e2)
    assert f"id: {e2.id}" in text
    assert "event: node.completed" in text
    assert '"n":2' in text

    # reconnect path increments counter when streaming from last id
    gen = hub.stream(last_event_id=e1.id)
    first = await gen.__anext__()
    assert first.id == e2.id
    metrics = metrics_payload().decode("utf-8")
    assert "dramaforge_sse_reconnect_total" in metrics
