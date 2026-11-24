"""Domain event emission for research and knowledge decisions.

Every accepted decision writes one EventLog row and one OutboxEvent in the caller's
transaction; payloads carry stable identities and versions only, never private
fragments, object keys or credentials. SSE consumers relay the outbox topic.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.service import EventService


async def emit(
    session: AsyncSession,
    *,
    project_id: UUID | None,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    payload: dict[str, object],
    actor_id: UUID | None,
) -> None:
    await EventService(session).append_with_outbox(
        project_id=project_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        topic=event_type,
        payload=payload,
        actor_id=actor_id,
    )


__all__ = ["emit"]
