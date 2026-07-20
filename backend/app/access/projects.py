"""Project create/read service (S1.2). App-layer authz; PG RLS is a separate Gate."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import (
    OrganizationMember,
    Project,
    ProjectMember,
    User,
    UserProjectPreference,
)
from app.shared.enums import ExperienceMode, MemberRole, ProjectStage
from app.shared.errors import ForbiddenError, NotFoundError, ValidationAppError


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _require_org_member(self, *, organization_id: UUID, user_id: UUID) -> None:
        result = await self._session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise ForbiddenError("not a member of this organization")

    async def create_project(
        self,
        *,
        organization_id: UUID,
        name: str,
        aspect_ratio: str,
        actor: User,
        budget_limit: Decimal = Decimal("0"),
        budget_currency: str = "USD",
        target_platform: str = "general",
    ) -> Project:
        if aspect_ratio not in {"9:16", "16:9"}:
            raise ValidationAppError("aspect_ratio must be 9:16 or 16:9")
        if budget_limit < 0:
            raise ValidationAppError("budget_limit must be >= 0")
        await self._require_org_member(organization_id=organization_id, user_id=actor.id)
        project = Project(
            organization_id=organization_id,
            name=name,
            stage=ProjectStage.DRAFT.value,
            aspect_ratio=aspect_ratio,
            target_platform=target_platform,
            style_bible={},
            budget_limit=budget_limit,
            budget_currency=budget_currency,
            provider_dispatch_frozen=False,
        )
        self._session.add(project)
        await self._session.flush()
        self._session.add(
            ProjectMember(
                project_id=project.id,
                user_id=actor.id,
                role=MemberRole.OWNER.value,
            )
        )
        self._session.add(
            UserProjectPreference(
                user_id=actor.id,
                project_id=project.id,
                experience_mode=ExperienceMode.WORKBENCH.value,
            )
        )
        await self._session.commit()
        await self._session.refresh(project)
        return project

    async def get_project_for_member(self, *, project_id: UUID, actor: User) -> Project:
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            raise NotFoundError("project not found")
        member = await self._session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == actor.id,
            )
        )
        if member.scalar_one_or_none() is None:
            raise ForbiddenError("not a member of this project")
        return project

    async def set_experience_mode(
        self, *, project_id: UUID, actor: User, mode: ExperienceMode
    ) -> UserProjectPreference:
        await self.get_project_for_member(project_id=project_id, actor=actor)
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
                experience_mode=mode.value,
            )
            self._session.add(pref)
        else:
            pref.experience_mode = mode.value
        await self._session.commit()
        await self._session.refresh(pref)
        return pref
