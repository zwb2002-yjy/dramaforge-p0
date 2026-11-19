"""Director-side notice port for MasterRun facts.

The production layer owns the ingestion/notice helper, but the Director layer may
only depend on ``shared``/``contract``. This port writes the same additive
outbox event with the same canonical notice models and topic string, so the
wire contract stays single-sourced while no new cross-layer import is created.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.domain_events import ProductionNotice, notice_scope
from app.events.service import EventService

PRODUCTION_FACT_TOPIC = "production.facts.v1"


async def append_master_run_notice(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
    notice: ProductionNotice,
) -> UUID:
    aggregate_type, aggregate_id = notice_scope(notice)
    log, _outbox = await EventService(session).append_with_outbox(
        project_id=project_id,
        actor_id=actor_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=notice.kind,
        topic=PRODUCTION_FACT_TOPIC,
        payload={
            "project_id": str(project_id),
            "actor_id": str(actor_id),
            "notice": notice.model_dump(mode="json"),
        },
    )
    return log.event_id


__all__ = ["append_master_run_notice"]
