"""Process a persisted notice in a director-owned, retryable transaction."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.models import Project, User
from app.contracts.director_runtime import ResumeSignal, RuntimeScope
from app.contracts.domain_events import (
    ExecutionAccepted,
    ExecutionChanged,
    FormalSelected,
    ProductionEvent,
    ProposalDecided,
)
from app.director.business_checkpoints import DirectorBusinessCheckpoints
from app.director.inbox_models import DirectorInbox, DirectorWakeup
from app.director.runtime.wakeups import DirectorRuntimeWakeupService
from app.director.turn_models import DirectorTurn
from app.events.models import EventLog
from app.production.application.facts import ProductionFacts
from app.shared.db import set_rls_context
from app.shared.errors import NotFoundError


async def process_director_wakeup(
    factory: async_sessionmaker[AsyncSession],
    *,
    inbox_id: UUID,
) -> bool:
    async with factory() as session:
        scopes = await session.execute(
            text("SELECT * FROM app.pending_director_wakeups(:inbox_id)"), {"inbox_id": inbox_id}
        )
        scope = scopes.mappings().one_or_none()
        if scope is None:
            return False
        await set_rls_context(
            session,
            user_id=scope["owner_user_id"],
            workspace_id=scope["workspace_id"],
            project_id=scope["project_id"],
        )
        processed = await apply_director_wakeup(session, inbox_id=inbox_id)
        await session.commit()
        return processed


async def apply_director_wakeup(session: AsyncSession, *, inbox_id: UUID) -> bool:
    """Apply within an already scoped director transaction; caller commits."""
    wakeup = await session.scalar(
        select(DirectorWakeup)
        .where(
            DirectorWakeup.inbox_id == inbox_id,
            DirectorWakeup.completed_at.is_(None),
            DirectorWakeup.dead_letter_at.is_(None),
            DirectorWakeup.next_attempt_at <= datetime.now(UTC),
        )
        .with_for_update(skip_locked=True)
    )
    if wakeup is None:
        return False
    wakeup.attempt_count += 1
    await session.flush()
    try:
        async with session.begin_nested():
            await _update_checkpoint(session, wakeup=wakeup)
        return True
    except Exception as exc:
        await session.refresh(wakeup)
        wakeup.last_error = type(exc).__name__[:120]
        now = datetime.now(UTC)
        if wakeup.attempt_count >= 5:
            wakeup.dead_letter_at = now
        else:
            wakeup.next_attempt_at = now + timedelta(seconds=min(300, 5 * 2**wakeup.attempt_count))
        await session.flush()
        return False


async def _update_checkpoint(session: AsyncSession, *, wakeup: DirectorWakeup) -> None:
    inbox_id = wakeup.inbox_id
    inbox = await session.get(DirectorInbox, inbox_id)
    if inbox is None:
        raise NotFoundError("Director event receipt missing")
    log = await session.scalar(
        select(EventLog).where(
            EventLog.event_id == inbox.event_id,
            EventLog.project_id == wakeup.project_id,
        )
    )
    if log is None:
        raise NotFoundError("Director event missing")
    event = ProductionEvent.model_validate(
        {
            "event_id": log.event_id,
            "project_id": log.project_id,
            "actor_id": log.actor_id,
            "schema_version": log.schema_version,
            "payload": log.payload.get("notice"),
        }
    )
    project = await session.get(Project, wakeup.project_id)
    actor = await session.get(User, event.actor_id)
    if project is None or actor is None:
        raise NotFoundError("Director event scope missing")
    await _enqueue_runtime_event(session, event=event)
    checkpoints = DirectorBusinessCheckpoints(session)
    if isinstance(event.payload, ExecutionAccepted):
        fact = await ProductionFacts(session).tracking(
            project_id=project.id,
            run_id=event.payload.node_run_id,
        )
        if fact.shot_id != event.payload.shot_id:
            raise ValueError("Event shot differs from production scope")
        await checkpoints.track_fact(project=project, actor=actor, run=fact)
    if isinstance(event.payload, ProposalDecided):
        await checkpoints.reconcile_business_fact(
            project=project, proposal_id=event.payload.proposal_id,
        )
    else:
        await checkpoints.reconcile_business_fact(project=project, shot_id=event.payload.shot_id)
    wakeup.completed_at = datetime.now(UTC)
    await session.flush()


async def _enqueue_runtime_event(
    session: AsyncSession, *, event: ProductionEvent,
) -> None:
    payload = event.payload
    if not isinstance(payload, (ExecutionChanged, FormalSelected, ProposalDecided)):
        return
    statement = select(DirectorTurn).where(
        DirectorTurn.project_id == event.project_id,
        DirectorTurn.runtime_execution_id.is_not(None),
        DirectorTurn.runtime_revision.is_not(None),
    )
    if isinstance(payload, ProposalDecided):
        statement = statement.where(
            DirectorTurn.proposal_id == payload.proposal_id,
            DirectorTurn.status == "awaiting_user",
        )
    elif isinstance(payload, ExecutionChanged):
        statement = statement.where(DirectorTurn.status == "awaiting_execution")
    else:
        statement = statement.where(
            DirectorTurn.scope_type == "shot",
            DirectorTurn.scope_entity_id == payload.shot_id,
            DirectorTurn.status == "awaiting_user",
            DirectorTurn.wait_reason == "confirm_candidate",
        )
    turns = list((await session.scalars(statement.order_by(DirectorTurn.id))).all())
    queue = DirectorRuntimeWakeupService(session)
    for turn in turns:
        if isinstance(payload, ExecutionChanged) and str(payload.node_run_id) not in {
            str(item) for item in turn.node_run_ids
        }:
            continue
        if isinstance(payload, FormalSelected):
            if len(turn.node_run_ids or []) != 1:
                continue
            tracking = await ProductionFacts(session).tracking(
                project_id=turn.project_id,
                run_id=UUID(str(turn.node_run_ids[0])),
            )
            if (
                tracking.result_artifact_id != payload.artifact_id
                or tracking.stage != payload.stage
            ):
                continue
        assert turn.runtime_execution_id is not None
        assert turn.runtime_revision is not None
        signal = ResumeSignal(
            scope=RuntimeScope(
                workspace_id=turn.workspace_id,
                project_id=turn.project_id,
                actor_id=turn.actor_id,
            ),
            turn_id=turn.id,
            signal_id=event.event_id,
            reason=("production_fact" if isinstance(payload, ExecutionChanged)
                    else "user_decision"),
            reference_id=event.event_id,
            expected_revision=turn.runtime_revision,
        )
        await queue.enqueue_resume(
            signal, runtime_execution_id=turn.runtime_execution_id,
        )
