"""Owner-triggered recovery of failed asynchronous work.

Two persisted failures can be replayed, and only these two:

- a Director wakeup the inbox worker dead-lettered,
- an Outbox event that exhausted its publish attempts.

Every replay is explicit (the caller must present the failure identity it saw,
so a stale page cannot reset a newer failure), owner-scoped, idempotent and
recorded as an audit event. There is no blind replay and no bulk replay.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import InstanceBootstrapState, Project, User, Workspace
from app.access.projects import ProjectService
from app.config import get_settings
from app.director.inbox_models import DirectorWakeup
from app.director.wakeup_replay import replay_failed_wakeup
from app.events.models import OutboxDeadLetter, OutboxEvent
from app.events.outbox import OutboxDispatcher, StreamPublisher
from app.events.service import EventService
from app.runtime.scheduler import RedisStreamPublisher
from app.shared.enums import OutboxStatus
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError

_RECOVERY_LIMIT = 50


class RecoveryItem(BaseModel):
    """One persisted failure the Owner may replay."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["director_wakeup", "outbox_dead_letter"]
    id: UUID
    project_id: UUID | None
    label: str
    detail: str
    attempts: int
    failed_at: datetime


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _is_instance_owner(session: AsyncSession, *, actor: User) -> bool:
    state = await session.get(InstanceBootstrapState, 1)
    return state is not None and state.owner_user_id == actor.id


async def _owned_project_ids(session: AsyncSession, *, actor: User) -> list[UUID]:
    rows = await session.execute(
        select(Project.id)
        .join(Workspace, Workspace.id == Project.workspace_id)
        .where(Workspace.owner_user_id == actor.id)
    )
    return [row[0] for row in rows.all()]


async def list_recovery_items(
    session: AsyncSession, *, actor: User
) -> list[RecoveryItem]:
    """Failures the current Owner can still replay, newest first.

    Items whose failure was already replayed are not actionable and stay out of
    the list: a dead-lettered wakeup has its ``dead_letter_at`` cleared, and a
    replayed Outbox event is back to ``published``.
    """
    project_ids = await _owned_project_ids(session, actor=actor)
    instance_owner = await _is_instance_owner(session, actor=actor)
    items: list[RecoveryItem] = []

    if project_ids:
        wakeups = (
            await session.execute(
                select(DirectorWakeup)
                .where(
                    DirectorWakeup.project_id.in_(project_ids),
                    DirectorWakeup.dead_letter_at.is_not(None),
                    DirectorWakeup.completed_at.is_(None),
                )
                .order_by(DirectorWakeup.dead_letter_at.desc())
                .limit(_RECOVERY_LIMIT)
            )
        ).scalars().all()
        for wakeup in wakeups:
            assert wakeup.dead_letter_at is not None
            items.append(
                RecoveryItem(
                    kind="director_wakeup",
                    id=wakeup.inbox_id,
                    project_id=wakeup.project_id,
                    label="director.wakeup",
                    detail=wakeup.last_error or "wakeup dead-lettered",
                    attempts=wakeup.attempt_count,
                    failed_at=_as_utc(wakeup.dead_letter_at),
                )
            )

    dead_letter_scope = [OutboxEvent.status != OutboxStatus.PUBLISHED.value]
    owner_scope = []
    if project_ids:
        owner_scope.append(OutboxDeadLetter.project_id.in_(project_ids))
    if instance_owner:
        owner_scope.append(OutboxDeadLetter.project_id.is_(None))
    if owner_scope:
        dead_letters = (
            await session.execute(
                select(OutboxDeadLetter, OutboxEvent.status)
                .join(OutboxEvent, OutboxEvent.id == OutboxDeadLetter.outbox_event_id)
                .where(*dead_letter_scope, or_(*owner_scope))
                .order_by(OutboxDeadLetter.dead_lettered_at.desc())
                .limit(_RECOVERY_LIMIT)
            )
        ).all()
        for dead_letter, _status in dead_letters:
            items.append(
                RecoveryItem(
                    kind="outbox_dead_letter",
                    id=dead_letter.id,
                    project_id=dead_letter.project_id,
                    label=dead_letter.topic,
                    detail=dead_letter.last_error_summary,
                    attempts=dead_letter.attempt_count,
                    failed_at=_as_utc(dead_letter.dead_lettered_at),
                )
            )

    items.sort(key=lambda item: item.failed_at, reverse=True)
    return items[:_RECOVERY_LIMIT]


async def replay_director_wakeup(
    session: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    inbox_id: UUID,
    expected_dead_letter_at: datetime,
) -> bool:
    """Replay one dead-lettered wakeup; False when it is no longer actionable."""
    return await replay_failed_wakeup(
        session,
        actor=actor,
        project_id=project_id,
        inbox_id=inbox_id,
        expected_dead_letter_at=_as_utc(expected_dead_letter_at),
    )


async def _require_dead_letter_owner(
    session: AsyncSession, *, actor: User, dead_letter: OutboxDeadLetter
) -> None:
    if dead_letter.project_id is not None:
        await ProjectService(session).get_project_for_owner(
            project_id=dead_letter.project_id, actor=actor
        )
        return
    if not await _is_instance_owner(session, actor=actor):
        raise ForbiddenError("only the instance Owner may replay this dead letter")


async def replay_outbox_dead_letter(
    session: AsyncSession,
    *,
    actor: User,
    dead_letter_id: UUID,
    expected_dead_lettered_at: datetime,
    publisher: StreamPublisher | None = None,
) -> tuple[OutboxEvent, bool]:
    """Replay one dead-lettered Outbox event exactly once, with an audit event.

    ``expected_dead_lettered_at`` is the failure identity the caller saw. A
    replay after a newer failure of the same event is a conflict, never a
    silent reset.
    """
    dead_letter = await session.scalar(
        select(OutboxDeadLetter)
        .where(OutboxDeadLetter.id == dead_letter_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if dead_letter is None:
        raise NotFoundError("outbox dead letter not found")
    await _require_dead_letter_owner(session, actor=actor, dead_letter=dead_letter)
    failed_at = _as_utc(dead_letter.dead_lettered_at)
    if _as_utc(expected_dead_lettered_at) != failed_at:
        raise ConflictError("outbox failure changed; reload before replay")

    current = await session.scalar(
        select(OutboxEvent).where(OutboxEvent.event_id == dead_letter.event_id)
    )
    applied = current is None or current.status != OutboxStatus.PUBLISHED.value

    redis_publisher: RedisStreamPublisher | None = None
    active_publisher = publisher
    if active_publisher is None:
        redis_publisher = RedisStreamPublisher(get_settings().redis_url)
        active_publisher = redis_publisher
    try:
        event = await OutboxDispatcher(
            session, publisher=active_publisher
        ).human_replay_dead_letter(dead_letter_id, operator=f"owner:{actor.id}")
    finally:
        if redis_publisher is not None:
            await redis_publisher.close()

    if not applied:
        # Idempotent no-op: the event is already published, so nothing was
        # replayed and nothing is claimed in the audit log.
        return event, False

    await EventService(session).append_with_outbox(
        project_id=dead_letter.project_id,
        aggregate_type="outbox_event",
        aggregate_id=dead_letter.event_id,
        event_type="outbox.dead_letter.replayed",
        topic="outbox.dead_letter.replayed",
        payload={
            "dead_letter_id": str(dead_letter.id),
            "event_id": str(dead_letter.event_id),
            "topic": dead_letter.topic,
            "failed_at": failed_at.isoformat(),
            "previous_attempts": dead_letter.attempt_count,
        },
        actor_id=actor.id,
    )
    await session.flush()
    return event, True
