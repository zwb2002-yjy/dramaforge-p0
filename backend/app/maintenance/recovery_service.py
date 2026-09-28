"""Owner-triggered recovery of failed asynchronous work.

Three persisted failures can be replayed, and only these three:

- a Director wakeup the inbox worker dead-lettered,
- an Outbox event that exhausted its publish attempts,
- a media NodeRun that failed after its remote task already existed (for example
  a provider result whose download hit a transient network error). Replaying it
  resumes the stored execution identity and polls the existing remote task; it
  never submits a second paid generation.

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
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.runtime.scheduler import NodeRunScheduler, RedisStreamPublisher
from app.shared.enums import OutboxStatus
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError

_RECOVERY_LIMIT = 50


class RecoveryItem(BaseModel):
    """One persisted failure the Owner may replay."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["director_wakeup", "outbox_dead_letter", "media_node_run"]
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

    if project_ids:
        # A media run that failed after its remote task existed can still be
        # finished by polling that task; a run that never reached the provider
        # has nothing to resume and is not offered here.
        resumable = (
            await session.execute(
                select(NodeRun, GraphNode.node_key)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(
                    NodeRun.project_id.in_(project_ids),
                    NodeRun.status == "failed",
                    NodeRun.finished_at.is_not(None),
                    NodeRun.result_artifact_id.is_(None),
                    NodeRun.id.in_(
                        select(ProviderOperation.node_run_id).where(
                            ProviderOperation.provider_operation_id.is_not(None)
                        )
                    ),
                )
                .order_by(NodeRun.finished_at.desc())
                .limit(_RECOVERY_LIMIT)
            )
        ).all()
        for run, node_key in resumable:
            assert run.finished_at is not None
            items.append(
                RecoveryItem(
                    kind="media_node_run",
                    id=run.id,
                    project_id=run.project_id,
                    label=node_key,
                    detail=run.error_summary or run.error_code or "generation failed",
                    attempts=run.attempt_no,
                    failed_at=_as_utc(run.finished_at),
                )
            )

    items.sort(key=lambda item: item.failed_at, reverse=True)
    return items[:_RECOVERY_LIMIT]


async def replay_media_node_run(
    session: AsyncSession,
    *,
    actor: User,
    project_id: UUID,
    node_run_id: UUID,
    expected_failed_at: datetime,
) -> bool:
    """Resume one failed media generation over its existing remote task.

    The run is reset to ``queued`` and handed back to the normal dispatcher: the
    worker resumes the persisted execution identity and polls the remote task it
    already created, so no second paid submission can happen.  ``False`` means
    the failure is no longer replayable exactly as the caller saw it.
    """
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=actor)
    run = await session.scalar(
        select(NodeRun).where(NodeRun.id == node_run_id, NodeRun.project_id == project_id)
    )
    if run is None:
        raise NotFoundError("node run not found")
    if run.status != "failed" or run.result_artifact_id is not None:
        return False
    failed_at = _as_utc(run.finished_at) if run.finished_at is not None else None
    if failed_at is None:
        return False
    if failed_at != _as_utc(expected_failed_at):
        raise ConflictError(
            "this run's failure changed since the page was loaded",
            details={"code": "RECOVERY_STALE_FAILURE"},
        )
    operation = await session.scalar(
        select(ProviderOperation)
        .where(
            ProviderOperation.node_run_id == node_run_id,
            ProviderOperation.provider_operation_id.is_not(None),
        )
        .order_by(ProviderOperation.attempt_no.desc())
        .limit(1)
    )
    if operation is None:
        # Nothing remote to resume: a fresh retry would be a new paid
        # submission, which this surface deliberately does not perform.
        raise ConflictError(
            "this failure has no remote task to resume",
            details={"code": "RECOVERY_NOT_RESUMABLE"},
        )
    previous_status = run.status
    run.status = "queued"
    run.error_code = None
    run.error_summary = None
    run.finished_at = None
    await session.flush()
    await NodeRunScheduler(session).enqueue_node_run_only(node_run_id)
    run.output_summary = {
        **(run.output_summary or {}),
        "recovery": {
            "replayed_from": previous_status,
            "operation_id": str(operation.id),
            "resumed": True,
        },
    }
    settings = get_settings()
    if settings.app_env != "test":
        await EventService(session).append_with_outbox(
            project_id=project_id,
            aggregate_type="node_run",
            aggregate_id=node_run_id,
            event_type="maintenance.media_node_run.replayed",
            topic="maintenance.media_node_run.replayed",
            payload={
                "node_run_id": str(node_run_id),
                "provider_operation_id": str(operation.id),
                "actor_id": str(actor.id),
            },
        )
    return True

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
