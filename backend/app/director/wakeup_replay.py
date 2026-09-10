"""Explicit owner replay of one failed wakeup generation, with an audit event."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.director.inbox_models import DirectorWakeup
from app.events.service import EventService
from app.shared.errors import ConflictError, NotFoundError


async def replay_failed_wakeup(
    session: AsyncSession, *, actor: User, project_id: UUID, inbox_id: UUID,
    expected_dead_letter_at: datetime,
) -> bool:
    """Caller commits; an old replay cannot reset a later failed generation."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=actor)
    row = await session.scalar(select(DirectorWakeup).where(
        DirectorWakeup.inbox_id == inbox_id, DirectorWakeup.project_id == project_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise NotFoundError("Director wakeup not found")
    if row.dead_letter_at is None or row.completed_at is not None:
        return False
    failed_at = row.dead_letter_at
    if failed_at.tzinfo is None:
        failed_at = failed_at.replace(tzinfo=UTC)
    if expected_dead_letter_at != failed_at:
        raise ConflictError("Director wakeup failure changed; reload before replay")
    await EventService(session).append_with_outbox(
        project_id=project_id, actor_id=actor.id, aggregate_type="director_wakeup",
        aggregate_id=inbox_id, event_type="director.wakeup.replayed",
        topic="director.wakeup.replayed",
        payload={"inbox_id": str(inbox_id), "failed_at": failed_at.isoformat(),
                 "previous_attempts": row.attempt_count},
    )
    row.attempt_count = 0
    row.dead_letter_at = None
    row.last_error = None
    row.next_attempt_at = datetime.now(UTC)
    await session.flush()
    return True
