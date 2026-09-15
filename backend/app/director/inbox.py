"""Durable event intake; ACK is permitted only after the caller commits."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.domain_events import ProductionEvent, notice_scope
from app.director.inbox_models import DirectorInbox, DirectorWakeup
from app.events.models import EventLog
from app.shared.errors import NotFoundError

DIRECTOR_CONSUMER_ID = "director-production-v1"


async def receive_production_event(
    session: AsyncSession, *, project_id: UUID, event_id: UUID,
) -> UUID:
    """Re-read the authenticated durable event, never trust a stream's payload.

    The caller establishes database RLS from trusted event ownership discovery.
    A duplicate cannot recreate a completed wakeup. Failure to enqueue after
    commit is recoverable by scanning wakeups whose completed_at is NULL.
    """
    log = await session.scalar(select(EventLog).where(
        EventLog.event_id == event_id, EventLog.project_id == project_id,
    ))
    if log is None:
        raise NotFoundError("Production event not found")
    event = ProductionEvent.model_validate({
        "event_id": log.event_id, "project_id": log.project_id,
        "actor_id": log.actor_id, "schema_version": log.schema_version,
        "payload": log.payload.get("notice"),
    })
    aggregate_type, aggregate_id = notice_scope(event.payload)
    if (log.event_type != event.payload.kind or log.aggregate_id != aggregate_id
            or log.aggregate_type != aggregate_type):
        raise ValueError("Production event metadata does not match its notice")
    lookup = select(DirectorInbox).where(
        DirectorInbox.consumer_id == DIRECTOR_CONSUMER_ID, DirectorInbox.event_id == event_id,
        DirectorInbox.project_id == project_id,
    )
    existing = await session.scalar(lookup)
    if existing is not None:
        return existing.id
    try:
        async with session.begin_nested():
            inbox = DirectorInbox(
                project_id=project_id, consumer_id=DIRECTOR_CONSUMER_ID, event_id=event_id,
            )
            session.add(inbox)
            await session.flush()
            session.add(DirectorWakeup(inbox_id=inbox.id, project_id=project_id))
            await session.flush()
        return inbox.id
    except IntegrityError:
        # Only an actually persisted winner explains a uniqueness race;
        # unrelated constraint failures must propagate.
        winner = await session.scalar(lookup)
        if winner is None:
            raise
        return winner.id
