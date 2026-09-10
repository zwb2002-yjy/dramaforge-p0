"""Production notices committed with the business fact, independent of director."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.domain_events import ProductionNotice, notice_scope
from app.events.service import EventService

PRODUCTION_FACT_TOPIC = "production.facts.v1"


async def append_production_notice(
    session: AsyncSession, *, project_id: UUID, actor_id: UUID,
    notice: ProductionNotice,
) -> UUID:
    # The existing outbox supplies event_id/schema_version in its envelope.
    # Consumers must authorize the persisted project and re-read its facts;
    # this notice never supplies an executable command or arbitrary graph state.
    aggregate_type, aggregate_id = notice_scope(notice)
    log, _outbox = await EventService(session).append_with_outbox(
        project_id=project_id, actor_id=actor_id, aggregate_type=aggregate_type,
        aggregate_id=aggregate_id, event_type=notice.kind,
        topic=PRODUCTION_FACT_TOPIC,
        payload={"project_id": str(project_id), "actor_id": str(actor_id),
                 "notice": notice.model_dump(mode="json")},
    )
    return log.event_id
