"""P1-01 workspace state persistence and restore for the professional shell."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User, UserProjectPreference
from app.access.projects import ProjectService
from app.shared.enums import ExperienceMode
from app.shared.errors import ValidationAppError


class WorkspaceStateService:
    """Per-user project workspace state used for last-view restore and panels.

    The state is a JSON object on ``UserProjectPreference``; patches merge into
    the existing object so the frontend can persist view/shot/panel facts
    independently without a second source of truth.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_preference(
        self, *, project_id: UUID, actor: User
    ) -> UserProjectPreference:
        await ProjectService(self._session).get_project_for_owner(
            project_id=project_id, actor=actor
        )
        result = await self._session.execute(
            select(UserProjectPreference).where(
                UserProjectPreference.user_id == actor.id,
                UserProjectPreference.project_id == project_id,
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = UserProjectPreference(
                user_id=actor.id,
                project_id=project_id,
                experience_mode=ExperienceMode.WORKBENCH.value,
            )
            self._session.add(pref)
            await self._session.flush()
        return pref

    async def get_workspace_state(
        self, *, project_id: UUID, actor: User
    ) -> dict[str, object]:
        pref = await self._get_preference(project_id=project_id, actor=actor)
        return dict(pref.workspace_state or {})

    async def update_workspace_state(
        self,
        *,
        project_id: UUID,
        actor: User,
        state: dict[str, object],
    ) -> dict[str, object]:
        if not isinstance(state, dict):
            raise ValidationAppError("workspace state must be a JSON object")
        pref = await self._get_preference(project_id=project_id, actor=actor)
        merged = dict(pref.workspace_state or {})
        merged.update(state)
        pref.workspace_state = merged
        await self._session.flush()
        return dict(pref.workspace_state)
