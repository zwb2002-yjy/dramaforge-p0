"""Creation experience shell: start_project without text Provider (S1.5)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.events.service import EventService
from app.shared.enums import ExperienceMode


class CreationService:
    """Stable Interface subset: start_project does not call text providers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._events = EventService(session)

    async def start_project(
        self,
        *,
        organization_id: UUID,
        name: str,
        aspect_ratio: str,
        actor: User,
        experience_mode: ExperienceMode = ExperienceMode.QUICK,
    ) -> dict[str, object]:
        project = await self._projects.create_project(
            organization_id=organization_id,
            name=name,
            aspect_ratio=aspect_ratio,
            actor=actor,
            budget_limit=Decimal("0"),
        )
        await self._projects.set_experience_mode(
            project_id=project.id, actor=actor, mode=experience_mode
        )
        # Re-open transactional write for event+outbox after project commits.
        log, outbox = await self._events.append_with_outbox(
            project_id=project.id,
            aggregate_type="project",
            aggregate_id=project.id,
            event_type="project.started",
            topic="project.started",
            payload={
                "project_id": str(project.id),
                "experience_mode": experience_mode.value,
                "provider_calls": 0,
            },
            actor_id=actor.id,
        )
        await self._session.commit()
        return {
            "project_id": project.id,
            "experience_mode": experience_mode.value,
            "event_id": log.event_id,
            "outbox_id": outbox.id,
            "text_provider_operations": 0,
        }
