"""Project use cases for private user-owned workspaces."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import (
    Project,
    ProjectCreativeProfile,
    User,
    UserProjectPreference,
    Workspace,
)
from app.access.project_intent import ProjectIntent, ProjectUpdateImpact, WorkType
from app.assets.models import Episode
from app.delivery.models import Export
from app.director.creative_capabilities.creative_compiler import CreativeCapabilityCompiler
from app.director.creative_capabilities.creative_templates import get_creative_template
from app.director.creative_capabilities.freeze import serialize_compiled_creative_intent
from app.director.creative_capabilities.packs_library import GENRE_PROFILES, STYLE_PACKS
from app.shared.db import set_rls_context
from app.shared.enums import ProjectStage
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationAppError,
)


def _project_name_conflict(name: str) -> ConflictError:
    return ConflictError(
        "当前空间已存在同名项目，请修改项目名后重试。",
        details={"code": "PROJECT_NAME_CONFLICT", "name": name},
    )


def _validated_project_update(
    project: Project, updates: dict[str, object], expected_version: int,
) -> tuple[str, ProjectIntent, ProjectIntent]:
    if not updates or set(updates) - {"name", *ProjectIntent.model_fields}:
        raise ValidationAppError("项目更新字段不正确")
    if any(
        updates.get(key, "") is None for key in ("name", "work_type", "creative_goal", "audience")
    ):
        raise ValidationAppError("项目名、作品类型和创作文字不能清空为null")
    if project.version != expected_version:
        raise ConflictError(
            "项目已更新，请刷新后重新确认。",
            details={"code": "PROJECT_VERSION_CONFLICT", "current_version": project.version},
        )
    current = ProjectIntent.model_validate(project)
    values = current.model_dump()
    values.update({key: value for key, value in updates.items() if key != "name"})
    try:
        desired = ProjectIntent.model_validate(values)
    except ValidationError as exc:
        raise ValidationAppError(
            "项目创作目标配置不正确", details={"code": "PROJECT_INTENT_INVALID"},
        ) from exc
    name = updates.get("name", project.name)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
        raise ValidationAppError("项目名必须为1至160个字符")
    return name.strip(), desired, current


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
        result = await self._session.execute(select(Workspace).where(Workspace.id == workspace_id))
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
        work_type: WorkType,
        creative_goal: str = "",
        audience: str = "",
        planned_duration_seconds: Decimal | None = None,
        planned_episode_count: int | None = None,
        budget_limit: Decimal = Decimal("0"),
        budget_currency: str = "USD",
        target_platform: str = "general",
        start_type: str = "FREE",
        template_key: str | None = None,
        template_version: str | None = None,
        director_autonomy: str = "ASSIST",
        genre_key: str | None = None,
        style_key: str | None = None,
    ) -> Project:
        if work_type is None:
            raise ValidationAppError("请选择作品类型", details={"code": "WORK_TYPE_REQUIRED"})
        try:
            intent = ProjectIntent(
                work_type=work_type, creative_goal=creative_goal, audience=audience,
                planned_duration_seconds=planned_duration_seconds,
                planned_episode_count=planned_episode_count,
            )
        except ValidationError as exc:
            raise ValidationAppError(
                "项目创作目标配置不正确", details={"code": "PROJECT_INTENT_INVALID"},
            ) from exc
        name = name.strip()
        if not name or len(name) > 160:
            raise ValidationAppError("项目名必须为1至160个字符")
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
        genre = next((item for item in GENRE_PROFILES if item.genre_key == genre_key), None)
        style = next((item for item in STYLE_PACKS if item.style_key == style_key), None)
        if genre_key is not None and genre is None:
            raise ValidationAppError("不支持的创作类型")
        if style_key is not None and style is None:
            raise ValidationAppError("不支持的画面风格")
        await self._get_owned_workspace(workspace_id=workspace_id, actor=actor)
        existing_project_id = await self._session.scalar(
            select(Project.id).where(
                Project.workspace_id == workspace_id,
                Project.name == name,
                Project.deleted_at.is_(None),
            )
        )
        if existing_project_id is not None:
            raise _project_name_conflict(name)
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
            **intent.model_dump(),
        )
        self._session.add(project)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # The pre-check gives normal requests a useful response. The
            # database constraint remains authoritative for concurrent creates.
            if "uq_projects_workspace_name" not in str(exc):
                raise
            await self._session.rollback()
            raise _project_name_conflict(name) from exc
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
            selected_style_ids=(list(template.recommended_style_ids) if template else []),
            selected_skill_ids=(list(template.recommended_skill_ids) if template else []),
            selected_shot_language=(template.recommended_shot_language if template else None),
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
        # Only choices explicitly submitted by the creator become execution defaults.
        # A template's recommendations alone retain their existing proposal-only meaning.
        if genre is not None or style is not None:
            if genre is not None:
                profile.selected_genre = genre.genre_key
            if style is not None:
                profile.selected_style_ids = [style.style_key]
            profile.strategy_snapshot = {
                **dict(profile.strategy_snapshot or {}),
                "creative_capabilities": serialize_compiled_creative_intent(
                    CreativeCapabilityCompiler().compile(genre=genre, style=style)
                ),
            }
        self._session.add(profile)
        await self._session.flush()
        await self._session.refresh(project)
        return project

    async def get_creative_direction(
        self, *, project_id: UUID, actor: User
    ) -> tuple[int, str]:
        """Return the explicit project creative direction and profile version."""
        await self.get_project_for_owner(project_id=project_id, actor=actor)
        profile = await self._session.scalar(
            select(ProjectCreativeProfile).where(
                ProjectCreativeProfile.project_id == project_id
            )
        )
        if profile is None:
            raise NotFoundError("creative profile not found")
        direction = str((profile.strategy_snapshot or {}).get("creative_direction") or "")
        return profile.version, direction

    async def set_creative_direction(
        self,
        *,
        project_id: UUID,
        actor: User,
        expected_profile_version: int,
        direction: str,
    ) -> tuple[int, str]:
        """CAS one explicit direction note; never rewrites other strategy facts."""
        await self.get_project_for_owner(project_id=project_id, actor=actor)
        profile = await self._session.scalar(
            select(ProjectCreativeProfile)
            .where(ProjectCreativeProfile.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if profile is None:
            raise NotFoundError("creative profile not found")
        if profile.version != expected_profile_version:
            raise ConflictError(
                "creative profile changed",
                details={
                    "code": "CREATIVE_PROFILE_VERSION_CONFLICT",
                    "current": profile.version,
                },
            )
        profile.strategy_snapshot = {
            **dict(profile.strategy_snapshot or {}),
            "creative_direction": direction.strip(),
        }
        profile.version += 1
        await self._session.flush()
        return profile.version, direction.strip()
    async def update_project(
        self, *, project_id: UUID, actor: User, expected_version: int,
        updates: dict[str, object],
    ) -> Project:
        """CAS metadata update; never relabel or remove existing production facts."""
        await self.get_project_for_owner(project_id=project_id, actor=actor)
        project = await self._session.scalar(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update().execution_options(populate_existing=True)
        )
        if project is None:
            raise NotFoundError("project not found")
        name, intent, current_intent = _validated_project_update(project, updates, expected_version)
        impact = await self._update_impact(project, intent)
        if not impact.can_apply:
            details: dict[str, object] = {
                "code": "PROJECT_STRUCTURE_CONFLICT", "episode_count": impact.episode_count,
            }
            if impact.affected_export_id is not None:
                details["export_id"] = str(impact.affected_export_id)
            raise ConflictError(impact.blockers[0], details=details)
        await self._require_unique_name(project, name)
        if name == project.name and intent == current_intent:
            return project
        project.name = name
        for field, value in intent.model_dump().items():
            setattr(project, field, value)
        project.version += 1
        project.updated_at = datetime.now(UTC)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "uq_projects_workspace_name" not in str(exc):
                raise
            await self._session.rollback()
            raise _project_name_conflict(name) from exc
        return project

    async def preview_project_update(
        self, *, project_id: UUID, actor: User, expected_version: int, updates: dict[str, object],
    ) -> ProjectUpdateImpact:
        project = await self.get_project_for_owner(project_id=project_id, actor=actor)
        name, intent, _ = _validated_project_update(project, updates, expected_version)
        await self._require_unique_name(project, name)
        return await self._update_impact(project, intent)

    async def _update_impact(self, project: Project, intent: ProjectIntent) -> ProjectUpdateImpact:
        episode_count = int(await self._session.scalar(
            select(func.count()).select_from(Episode).where(Episode.project_id == project.id)
        ) or 0)
        if ((intent.work_type == "single_comic" and episode_count > 1)
                or (intent.planned_episode_count is not None
                    and episode_count > intent.planned_episode_count)):
            return ProjectUpdateImpact(
                project_id=project.id,
                project_version=project.version,
                episode_count=episode_count,
                can_apply=False,
                blockers=["现有分集超过新的作品计划，请先调整计划；不会自动删除分集。"],
            )
        if project.work_type is not None and intent.work_type != project.work_type:
            incompatible_scope = (
                Export.episode_id.is_not(None) if intent.work_type == "animation_promo"
                else Export.episode_id.is_(None)
            )
            incompatible_export = await self._session.scalar(
                select(Export.id).where(
                    Export.project_id == project.id, incompatible_scope,
                    or_(Export.status.in_(("queued", "running", "completed")),
                        Export.result_artifact_id.is_not(None)),
                ).limit(1)
            )
            if incompatible_export is not None:
                return ProjectUpdateImpact(
                    project_id=project.id, project_version=project.version,
                    episode_count=episode_count, can_apply=False,
                    blockers=["现有交付范围与新作品类型不兼容，不能直接改变正式交付的含义。"],
                    affected_export_id=incompatible_export,
                )
        return ProjectUpdateImpact(
            project_id=project.id, project_version=project.version,
            episode_count=episode_count, can_apply=True, blockers=[],
        )

    async def _require_unique_name(self, project: Project, name: str) -> None:
        if name != project.name:
            duplicate = await self._session.scalar(select(Project.id).where(
                Project.workspace_id == project.workspace_id, Project.name == name,
                Project.deleted_at.is_(None), Project.id != project.id,
            ))
            if duplicate is not None:
                raise _project_name_conflict(name)

    async def get_project_for_owner(self, *, project_id: UUID, actor: User) -> Project:
        result = await self._session.execute(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
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

    async def list_projects_for_owner(self, *, workspace_id: UUID, actor: User) -> list[Project]:
        await self._get_owned_workspace(workspace_id=workspace_id, actor=actor)
        result = await self._session.execute(
            select(Project)
            .where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc(), Project.id)
        )
        return list(result.scalars().all())

    async def lock_project_for_deletion(
        self,
        *,
        project_id: UUID,
        actor: User,
        expected_version: int,
    ) -> Project:
        await self.get_project_for_owner(project_id=project_id, actor=actor)
        project = await self._session.scalar(
            select(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if project is None:
            raise NotFoundError("project not found")
        if project.version != expected_version:
            raise ConflictError(
                "项目已发生变化，请刷新后重新确认删除。",
                details={"code": "PROJECT_VERSION_CONFLICT"},
            )
        return project
