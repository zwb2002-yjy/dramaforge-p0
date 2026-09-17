"""Owner recovery service: explicit, owner-scoped, idempotent, audited."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import InstanceBootstrapState, Project, User, Workspace
from app.director.inbox_models import DirectorInbox, DirectorWakeup
from app.events.models import EventLog, OutboxDeadLetter, OutboxEvent
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.maintenance import recovery_service
from app.shared.base import Base
from app.shared.enums import OutboxStatus, ProjectStage
from app.shared.errors import ConflictError, ForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def _make_env() -> tuple[object, AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory()


async def _seed_owner(session: AsyncSession) -> tuple[User, Project]:
    user = User(
        email=f"recovery-{uuid4().hex}@example.com",
        display_name="Owner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="W")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="P",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="16:9",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    return user, project


async def _seed_dead_lettered_wakeup(
    session: AsyncSession, *, owner: User, project: Project, failed_at: datetime
) -> DirectorWakeup:
    event = EventLog(
        project_id=project.id,
        aggregate_type="test",
        aggregate_id=uuid4(),
        event_type="test.event",
        schema_version=1,
        actor_id=owner.id,
        payload={},
    )
    session.add(event)
    await session.flush()
    inbox = DirectorInbox(
        project_id=project.id,
        consumer_id="director",
        event_id=event.event_id,
    )
    session.add(inbox)
    await session.flush()
    wakeup = DirectorWakeup(
        inbox_id=inbox.id,
        project_id=project.id,
        completed_at=None,
        attempt_count=5,
        next_attempt_at=failed_at,
        dead_letter_at=failed_at,
        last_error="RuntimeError",
    )
    session.add(wakeup)
    await session.flush()
    return wakeup


async def _seed_outbox_dead_letter(
    session: AsyncSession, *, project: Project, failed_at: datetime
) -> tuple[OutboxEvent, OutboxDeadLetter]:
    event = OutboxEvent(
        event_id=uuid4(),
        project_id=project.id,
        topic="production.execution_changed",
        schema_version=1,
        payload={"notice": {"kind": "execution_changed"}},
        status=OutboxStatus.DEAD_LETTER.value,
        attempt_count=3,
        next_attempt_at=failed_at,
        last_error_summary="redis unavailable",
    )
    session.add(event)
    await session.flush()
    dead_letter = OutboxDeadLetter(
        outbox_event_id=event.id,
        event_id=event.event_id,
        project_id=project.id,
        topic=event.topic,
        payload=event.payload,
        attempt_count=3,
        last_error_summary="redis unavailable",
        dead_lettered_at=failed_at,
    )
    session.add(dead_letter)
    await session.flush()
    return event, dead_letter


async def test_list_recovery_items_is_owner_scoped() -> None:
    engine, session = await _make_env()
    try:
        owner, project = await _seed_owner(session)
        session.add(InstanceBootstrapState(singleton_id=1, owner_user_id=owner.id))
        failed_at = datetime.now(UTC) - timedelta(minutes=5)
        await _seed_dead_lettered_wakeup(
            session, owner=owner, project=project, failed_at=failed_at
        )
        await _seed_outbox_dead_letter(session, project=project, failed_at=failed_at)

        items = await recovery_service.list_recovery_items(session, actor=owner)
        assert sorted(item.kind for item in items) == [
            "director_wakeup",
            "outbox_dead_letter",
        ]

        stranger = User(
            email=f"stranger-{uuid4().hex}@example.com",
            display_name="Stranger",
            password_hash="x",
        )
        session.add(stranger)
        await session.flush()
        assert await recovery_service.list_recovery_items(session, actor=stranger) == []
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]


async def test_replay_director_wakeup_requires_the_observed_failure() -> None:
    engine, session = await _make_env()
    try:
        owner, project = await _seed_owner(session)
        failed_at = datetime.now(UTC) - timedelta(minutes=5)
        wakeup = await _seed_dead_lettered_wakeup(
            session, owner=owner, project=project, failed_at=failed_at
        )

        with pytest.raises(ConflictError):
            await recovery_service.replay_director_wakeup(
                session,
                actor=owner,
                project_id=project.id,
                inbox_id=wakeup.inbox_id,
                expected_dead_letter_at=failed_at - timedelta(seconds=1),
            )

        assert await recovery_service.replay_director_wakeup(
            session,
            actor=owner,
            project_id=project.id,
            inbox_id=wakeup.inbox_id,
            expected_dead_letter_at=failed_at,
        )
        await session.flush()
        assert wakeup.dead_letter_at is None
        assert wakeup.attempt_count == 0

        # Already replayed: not actionable, and not an error.
        assert not await recovery_service.replay_director_wakeup(
            session,
            actor=owner,
            project_id=project.id,
            inbox_id=wakeup.inbox_id,
            expected_dead_letter_at=failed_at,
        )
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]


async def test_replay_outbox_dead_letter_audits_and_never_double_publishes() -> None:
    engine, session = await _make_env()
    try:
        owner, project = await _seed_owner(session)
        failed_at = datetime.now(UTC) - timedelta(minutes=5)
        _event, dead_letter = await _seed_outbox_dead_letter(
            session, project=project, failed_at=failed_at
        )
        publisher = StreamPublisher()

        with pytest.raises(ConflictError):
            await recovery_service.replay_outbox_dead_letter(
                session,
                actor=owner,
                dead_letter_id=dead_letter.id,
                expected_dead_lettered_at=failed_at + timedelta(seconds=1),
                publisher=publisher,
            )

        replayed, applied = await recovery_service.replay_outbox_dead_letter(
            session,
            actor=owner,
            dead_letter_id=dead_letter.id,
            expected_dead_lettered_at=failed_at,
            publisher=publisher,
        )
        assert applied is True
        assert replayed.status == OutboxStatus.PUBLISHED.value
        assert len(publisher.messages) == 1

        again, replayed_again = await recovery_service.replay_outbox_dead_letter(
            session,
            actor=owner,
            dead_letter_id=dead_letter.id,
            expected_dead_lettered_at=failed_at,
            publisher=publisher,
        )
        assert again.id == replayed.id
        assert replayed_again is False
        assert len(publisher.messages) == 1

        audits = (
            await session.execute(
                select(EventLog).where(
                    EventLog.event_type == "outbox.dead_letter.replayed"
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].actor_id == owner.id
        assert audits[0].payload["topic"] == "production.execution_changed"

        stranger = User(
            email=f"stranger-{uuid4().hex}@example.com",
            display_name="Stranger",
            password_hash="x",
        )
        session.add(stranger)
        await session.flush()
        with pytest.raises(ForbiddenError):
            await recovery_service.replay_outbox_dead_letter(
                session,
                actor=stranger,
                dead_letter_id=dead_letter.id,
                expected_dead_lettered_at=failed_at,
                publisher=publisher,
            )
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]


async def test_re_failure_after_replay_refreshes_the_same_dead_letter() -> None:
    """Failure -> dead letter -> owner replay -> new failure -> new dead letter."""
    engine, session = await _make_env()
    try:
        owner, project = await _seed_owner(session)
        failed_at = datetime.now(UTC) - timedelta(minutes=5)
        event, dead_letter = await _seed_outbox_dead_letter(
            session, project=project, failed_at=failed_at
        )
        await recovery_service.replay_outbox_dead_letter(
            session,
            actor=owner,
            dead_letter_id=dead_letter.id,
            expected_dead_lettered_at=failed_at,
            publisher=StreamPublisher(),
        )

        # The refreshed failure identity must make the stale page a conflict.
        dispatcher = OutboxDispatcher(session, publisher=StreamPublisher(), max_attempts=3)
        event.status = OutboxStatus.LEASED.value
        event.attempt_count = 3
        await session.flush()
        refreshed = await dispatcher.fail_leased(event, error="redis unavailable again")
        await session.flush()

        assert refreshed is not None
        rows = (
            await session.execute(
                select(OutboxDeadLetter).where(
                    OutboxDeadLetter.outbox_event_id == event.id
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == dead_letter.id
        assert rows[0].last_error_summary == "redis unavailable again"

        # The refreshed failure identity makes the stale page a conflict.
        with pytest.raises(ConflictError):
            await recovery_service.replay_outbox_dead_letter(
                session,
                actor=owner,
                dead_letter_id=dead_letter.id,
                expected_dead_lettered_at=failed_at,
                publisher=StreamPublisher(),
            )
    finally:
        await session.close()
        await engine.dispose()  # type: ignore[union-attr]
