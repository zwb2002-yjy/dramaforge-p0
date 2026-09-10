"""Real Redis redelivery after a committed PostgreSQL receipt and failed ACK."""

import os
from uuid import uuid4

import pytest
from app.contracts.domain_events import ExecutionAccepted
from app.director import event_consumer
from app.director.inbox_models import DirectorInbox, DirectorWakeup
from app.production.application.events import append_production_notice
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_director_turn_lifecycle_pg import _alembic, _async_url, _create_database, _drop_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark
from tests.unit.test_workbench_execution import _seed


@pytest.mark.skipif(not os.environ.get("TEST_DIRECTOR_REDIS_URL"), reason="isolated Redis required")
@pytest.mark.asyncio
async def test_commit_before_ack_and_reclaim_ignores_untrusted_payload(monkeypatch):
    dbname = f"dramaforge_d2_stream_{uuid4().hex[:8]}"
    stream = f"dramaforge:test:director:{uuid4().hex}"
    monkeypatch.setattr(event_consumer, "PRODUCTION_STREAM", stream)
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    redis = Redis.from_url(os.environ["TEST_DIRECTOR_REDIS_URL"], decode_responses=True)
    try:
        _alembic(dbname)
        admin = async_sessionmaker(engine, expire_on_commit=False)
        async with admin() as session:
            project, _binding, actor = await _seed(session)
            event_id = await append_production_notice(
                session, project_id=project.id, actor_id=actor.id,
                notice=ExecutionAccepted(shot_id=uuid4(), node_run_id=uuid4()),
            )
            await session.commit()
        await redis.xadd(stream, {
            "event_id": str(event_id), "project_id": str(uuid4()), "payload": "forged",
        })
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        consumer = event_consumer.DirectorEventConsumer(
            factory, redis, consumer_name="interrupted", reclaim_after_ms=0,
        )
        original_ack = redis.xack

        async def fail_ack(*args, **kwargs):
            raise ConnectionError("Injected connection loss after DB commit")

        monkeypatch.setattr(redis, "xack", fail_ack)
        with pytest.raises(ConnectionError):
            await consumer.poll_once()
        async with admin() as session:
            assert await session.scalar(select(func.count()).select_from(DirectorInbox)) == 1
            wakeup = await session.scalar(select(DirectorWakeup))
            assert wakeup.project_id == project.id and wakeup.completed_at is None
        pending = await redis.xpending(stream, event_consumer.DIRECTOR_CONSUMER_ID)
        assert pending["pending"] == 1
        monkeypatch.setattr(redis, "xack", original_ack)
        recovered = event_consumer.DirectorEventConsumer(
            factory, redis, consumer_name="replacement", reclaim_after_ms=0,
        )
        assert await recovered.poll_once() == 1
        assert (await redis.xpending(stream, event_consumer.DIRECTOR_CONSUMER_ID))["pending"] == 0
        async with admin() as session:
            assert await session.scalar(select(func.count()).select_from(DirectorInbox)) == 1
            assert await session.scalar(select(func.count()).select_from(DirectorWakeup)) == 1
        await redis.xadd(stream, {"event_id": "invalid-event"})
        await redis.xadd(stream, {"event_id": str(event_id)})
        assert await recovered.poll_once() == 1
        assert (await redis.xpending(stream, event_consumer.DIRECTOR_CONSUMER_ID))["pending"] == 1
        # A repeatedly failing reclaimed message does not starve new messages.
        await redis.xadd(stream, {"event_id": str(event_id)})
        assert await recovered.poll_once() == 1
        for _ in range(2):
            with pytest.raises(ValueError):
                await recovered.poll_once()
        await redis.set(f"{stream}:director-dead-letter", "injected-invalid-type")
        with pytest.raises(ResponseError):
            await recovered.poll_once()
        assert (await redis.xpending(stream, event_consumer.DIRECTOR_CONSUMER_ID))["pending"] == 1
        await redis.delete(f"{stream}:director-dead-letter")
        assert await recovered.poll_once() == 1
        assert (await redis.xpending(stream, event_consumer.DIRECTOR_CONSUMER_ID))["pending"] == 0
        dead = await redis.xrange(f"{stream}:director-dead-letter")
        assert len(dead) == 1
        assert dead[0][1]["event_id"] == ""
        assert dead[0][1]["error_type"] == "ValueError"
        assert "payload" not in dead[0][1]
    finally:
        await redis.delete(stream, f"{stream}:director-dead-letter")
        await redis.aclose()
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)


@pytest.mark.skipif(not os.environ.get("TEST_DIRECTOR_REDIS_URL"), reason="isolated Redis required")
@pytest.mark.asyncio
async def test_real_publish_before_database_commit_redelivers_one_inbox(monkeypatch):
    from app.events.models import OutboxEvent
    from app.events.outbox import OutboxDispatcher
    from app.runtime.scheduler import RedisStreamPublisher
    from app.shared.db import set_rls_context

    dbname = f"dramaforge_d2_publish_{uuid4().hex[:8]}"
    topic = f"test:director:{uuid4().hex}"
    stream = f"dramaforge:stream:{topic}"
    monkeypatch.setattr(event_consumer, "PRODUCTION_STREAM", stream)
    await _create_database(dbname)
    engine = create_async_engine(_async_url(dbname))
    app_engine = create_async_engine(
        _async_url(dbname), connect_args={"server_settings": {"role": "dramaforge_app"}},
    )
    redis = Redis.from_url(os.environ["TEST_DIRECTOR_REDIS_URL"], decode_responses=True)

    class IsolatedPublisher(RedisStreamPublisher):
        async def publish(self, original_topic, payload):
            assert original_topic == "production.facts.v1"
            # Only namespace the stream; use the deployed Redis implementation.
            return await super().publish(topic, payload)

    publisher = IsolatedPublisher(os.environ["TEST_DIRECTOR_REDIS_URL"])
    try:
        _alembic(dbname)
        admin = async_sessionmaker(engine, expire_on_commit=False)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        async with admin() as session:
            project, _binding, actor = await _seed(session)
            event_id = await append_production_notice(
                session, project_id=project.id, actor_id=actor.id,
                notice=ExecutionAccepted(shot_id=uuid4(), node_run_id=uuid4()),
            )
            await session.commit()
        # The director is stopped while publication is retried. A publish survives
        # rollback of the publisher's database transaction, as after a crash.
        for commit in (False, True):
            async with factory() as session:
                await set_rls_context(session, user_id=actor.id,
                                      workspace_id=project.workspace_id, project_id=project.id)
                dispatcher = OutboxDispatcher(session, publisher=publisher)
                event = await dispatcher.claim_one_by_event_id(
                    event_id=event_id, worker_id="publisher",
                )
                assert event is not None
                await dispatcher.publish_leased(event)
                if commit:
                    await session.commit()
                else:
                    await session.rollback()
            async with admin() as session:
                event = await session.scalar(select(OutboxEvent).where(
                    OutboxEvent.event_id == event_id,
                ))
                assert event.status == ("published" if commit else "pending")
                assert await session.scalar(select(func.count()).select_from(DirectorInbox)) == 0
        # Inspect Redis itself: the test-mode in-memory fallback cannot pass this.
        messages = await redis.xrange(stream)
        assert len(messages) == 2
        assert {fields["event_id"] for _id, fields in messages} == {str(event_id)}
        consumer = event_consumer.DirectorEventConsumer(
            factory, redis, consumer_name="restarted", reclaim_after_ms=0,
        )
        assert await consumer.poll_once() == 2
        assert (await redis.xpending(stream, event_consumer.DIRECTOR_CONSUMER_ID))["pending"] == 0
        async with admin() as session:
            assert await session.scalar(select(func.count()).select_from(DirectorInbox)) == 1
            assert await session.scalar(select(func.count()).select_from(DirectorWakeup)) == 1
            wakeup = await session.scalar(select(DirectorWakeup))
            assert wakeup.completed_at is None
    finally:
        await publisher.close()
        await redis.delete(stream)
        await redis.aclose()
        await app_engine.dispose()
        await engine.dispose()
        await _drop_database(dbname)
