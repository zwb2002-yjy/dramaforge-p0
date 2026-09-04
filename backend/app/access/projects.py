"""Project use cases for private user-owned workspaces."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import (
    Project,
    ProjectCreativeProfile,
    User,
    UserProjectPreference,
    Workspace,
)
from app.director.creative_capabilities.creative_templates import get_creative_template
from app.shared.db import set_rls_context
from app.shared.enums import ProjectStage
from app.shared.errors import ForbiddenError, NotFoundError, ValidationAppError


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _selected_workspace_id(self) -> UUID | None:
        value = self._session.info.get("selected_workspace_id")
        return value if isinstance(value, UUID) else None

    def _require_selected_workspace_match(self, workspace_id: UUID) -> None:
        selected_workspace_id = self._selected_workspace_id()
        if selected_workspace_id is not None and selected_workspace_id != workspace_id:
            # Hide projects/workspaces outside the active personal workspace,
            # including other workspaces owned by the same account.
            raise NotFoundError("workspace not found")

    async def _get_owned_workspace(self, *, workspace_id: UUID, actor: User) -> Workspace:
        self._require_selected_workspace_match(workspace_id)
        result = await self._session.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            raise NotFoundError("workspace not found")
        if workspace.owner_user_id != actor.id:
            raise ForbiddenError("workspace belongs to another user")
        return workspace

    async def create_project(
        self,
        *,
        workspace_id: UUID,
        name: str,
        aspect_ratio: str,
        actor: User,
        budget_limit: Decimal = Decimal("0"),
        budget_currency: str = "USD",
        target_platform: str = "general",
        start_type: str = "FREE",
        template_key: str | None = None,
        template_version: str | None = None,
        director_autonomy: str = "ASSIST",
    ) -> Project:
        if start_type not in {"TEMPLATE", "FREE"}:
            raise ValidationAppError("start_type must be TEMPLATE or FREE")
        if director_autonomy not in {"AUTO", "ASSIST", "MANUAL"}:
            raise ValidationAppError("director_autonomy must be AUTO, ASSIST, or MANUAL")
        if start_type == "TEMPLATE" and not template_key:
            raise ValidationAppError(
                "template start requires template_key",
                details={"code": "TEMPLATE_KEY_REQUIRED"},
            )
        if aspect_ratio not in {"9:16", "16:9"}:
            raise ValidationAppError("aspect_ratio must be 9:16 or 16:9")
        if budget_limit < 0:
            raise ValidationAppError("budget_limit must be >= 0")
        await self._get_owned_workspace(workspace_id=workspace_id, actor=actor)
        project = Project(
            workspace_id=workspace_id,
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
        await set_rls_context(
            self._session,
            user_id=actor.id,
            workspace_id=workspace_id,
            project_id=project.id,
        )
        self._session.add(
            UserProjectPreference(
                user_id=actor.id,
                project_id=project.id,
            )
        )
        await self._session.flush()
        template = None
        if start_type == "TEMPLATE" and template_key:
            template = get_creative_template(template_key, template_version)
        profile = ProjectCreativeProfile(
            project_id=project.id,
            start_type=start_type,
            created_from_template_key=template.key if template else None,
            template_version=template.version if template else None,
            template_contract_hash=template.contract_hash if template else None,
            director_autonomy=director_autonomy,
            selected_genre=template.recommended_genre if template else None,
            selected_style_ids=(
                list(template.recommended_style_ids) if template else []
            ),
            selected_skill_ids=(
                list(template.recommended_skill_ids) if template else []
            ),
            selected_shot_language=(
                template.recommended_shot_language if template else None
            ),
            asset_slot_requirements=(
                {
                    "required": list(template.required_asset_slots),
                    "optional": list(template.optional_asset_slots),
                }
                if template
                else {"required": [], "optional": []}
            ),
            strategy_snapshot=(
                dict(template.model_dump(mode="json"))
                if template
                else {
                    "source": "free",
                    "shot_planning": "user_directed",
                    "generation": "keyframe_then_video",
                    "review": "user_review",
                    "editing": "user_timeline",
                }
            ),
            version=1,
        )
        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(project)
        return project

    async def get_project_for_owner(self, *, project_id: UUID, actor: User) -> Project:
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            raise NotFoundError("project not found")
        self._require_selected_workspace_match(project.workspace_id)
        await self._get_owned_workspace(workspace_id=project.workspace_id, actor=actor)
        await set_rls_context(
            self._session,
            user_id=actor.id,
            workspace_id=project.workspace_id,
            project_id=project.id,
        )
        return project

    async def list_projects_for_owner(
        self, *, workspace_id: UUID, actor: User
    ) -> list[Project]:
        await self._get_owned_workspace(workspace_id=workspace_id, actor=actor)
        result = await self._session.execute(
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .order_by(Project.created_at.desc(), Project.id)
        )
        return list(result.scalars().all())
