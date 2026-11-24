"""Replay competes with another replay/dispatcher on real row locks, not sleeps."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.events.models import OutboxDeadLetter, OutboxEvent
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.shared.enums import OutboxStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_phase5_restart_recovery_pg import pg_session as pg_session
from test_phase5_restart_recovery_pg import pytestmark as pytestmark


@pytest.mark.asyncio
async def test_parallel_replays_publish_once_after_lock_wait(pg_session):
    event = OutboxEvent(event_id=uuid4(), topic="audit.replay", payload={},
                        status=OutboxStatus.DEAD_LETTER.value, attempt_count=3)
    pg_session.add(event)
    await pg_session.flush()
    letter = OutboxDeadLetter(outbox_event_id=event.id, event_id=event.event_id,
        topic=event.topic, payload={}, attempt_count=3, last_error_summary="offline")
    pg_session.add(letter)
    await pg_session.commit()
    letter_id, event_id = letter.id, event.id
    factory = async_sessionmaker(pg_session.bind, expire_on_commit=False)
    publishing, release, second_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    class Publisher(StreamPublisher):
        async def publish(self, topic, payload):
            publishing.set()
            await release.wait()
            return await super().publish(topic, payload)

    publisher = Publisher()

    async def replay(name):
        async with factory() as session:
            pids[name] = await session.scalar(text("SELECT pg_backend_pid()"))
            if name == "second":
                second_ready.set()
            await OutboxDispatcher(session, publisher).human_replay_dead_letter(
                letter_id, operator=name,
            )
            await session.commit()

    first = asyncio.create_task(replay("first"))
    second = None
    try:
        await asyncio.wait_for(publishing.wait(), timeout=10)
        second = asyncio.create_task(replay("second"))
        await asyncio.wait_for(second_ready.wait(), timeout=10)

        async def wait_for_row_lock():
            while True:
                blockers = await pg_session.scalar(text("SELECT pg_blocking_pids(:pid)"),
                                                   {"pid": pids["second"]})
                if pids["first"] in blockers:
                    return
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_row_lock(), timeout=10)
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
    assert len(publisher.messages) == 1
    pg_session.expire_all()
    final = await pg_session.get(OutboxEvent, event_id)
    assert final.status == "published" and final.attempt_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("known_expiry", [False, True])
async def test_replay_cannot_steal_a_live_dispatcher_lease(pg_session, known_expiry):
    from app.shared.errors import ConflictError

    event = OutboxEvent(event_id=uuid4(), topic="audit.live", payload={}, status="leased",
                        attempt_count=1, locked_by="dispatcher",
                        leased_until=(datetime.now(UTC) + timedelta(minutes=1)
                                      if known_expiry else None))
    pg_session.add(event)
    await pg_session.flush()
    letter = OutboxDeadLetter(outbox_event_id=event.id, event_id=event.event_id,
        topic=event.topic, payload={}, attempt_count=3, last_error_summary="old failure")
    pg_session.add(letter)
    await pg_session.commit()
    publisher = StreamPublisher()
    with pytest.raises(ConflictError):
        await OutboxDispatcher(pg_session, publisher).human_replay_dead_letter(
            letter.id, operator="owner",
        )
    assert publisher.messages == []
    assert event.locked_by == "dispatcher" and event.attempt_count == 1
