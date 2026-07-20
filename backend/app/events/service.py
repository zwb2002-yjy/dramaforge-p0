"""Transactional EventLog + Outbox writer (same session/commit)."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.models import EventLog, OutboxEvent
from app.shared.enums import OutboxStatus


class EventService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_with_outbox(
        self,
        *,
        project_id: UUID | None,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        topic: str,
        payload: dict,
        actor_id: UUID | None = None,
        schema_version: int = 1,
    ) -> tuple[EventLog, OutboxEvent]:
        """Write event_log and outbox_events rows; caller may commit with other work."""
        event_id = uuid4()
        log = EventLog(
            event_id=event_id,
            project_id=project_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            schema_version=schema_version,
            actor_id=actor_id,
            payload=payload,
        )
        outbox = OutboxEvent(
            event_id=event_id,
            project_id=project_id,
            topic=topic,
            schema_version=schema_version,
            payload=payload,
            status=OutboxStatus.PENDING.value,
            attempt_count=0,
        )
        self._session.add(log)
        self._session.add(outbox)
        await self._session.flush()
        return log, outbox

    async def list_pending_outbox(self) -> list[OutboxEvent]:
        result = await self._session.execute(
            select(OutboxEvent).where(OutboxEvent.status == OutboxStatus.PENDING.value)
        )
        return list(result.scalars().all())
