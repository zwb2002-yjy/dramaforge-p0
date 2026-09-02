"""Project HTTP routes (S1.2 + V1 CreativeTemplate profile)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.access.models import Project, ProjectCreativeProfile
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.api.v1 import workbench as _workbench
from app.shared.enums import ProjectStage
from app.shared.errors import ConflictError, NotFoundError

router = APIRouter(
    tags=["projects"], dependencies=[Depends(require_selected_workspace)]
)

router.include_router(_workbench.router)


class ProjectCreate(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=160)
    aspect_ratio: str = Field(pattern="^(9:16|16:9)$")
    target_platform: str = Field(default="general", max_length=40)
    start_type: Literal["TEMPLATE", "FREE"] = "FREE"
    template_key: str | None = Field(default=None, max_length=80)
    template_version: str | None = Field(default=None, max_length=40)
    director_autonomy: Literal["AUTO", "ASSIST", "MANUAL"] = "ASSIST"


class ProjectCreativeProfileRead(BaseModel):
    id: UUID
    project_id: UUID
    start_type: str
    created_from_template_key: str | None
    template_version: str | None
    template_contract_hash: str | None
    director_autonomy: str
    selected_genre: str | None
    selected_style_ids: list[str]
    selected_skill_ids: list[str]
    selected_shot_language: str | None
    asset_slot_requirements: dict[str, object]
    strategy_snapshot: dict[str, object]
    version: int


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    stage: ProjectStage
    aspect_ratio: str
    target_platform: str
    provider_dispatch_frozen: bool
    version: int
    creative_profile: ProjectCreativeProfileRead


class CreativeProfileUpdateBody(BaseModel):
    expected_version: int = Field(ge=1)
    director_autonomy: Literal["AUTO", "ASSIST", "MANUAL"]


def _profile_read(profile: ProjectCreativeProfile) -> ProjectCreativeProfileRead:
    return ProjectCreativeProfileRead(
        id=profile.id,
        project_id=profile.project_id,
        start_type=profile.start_type,
        created_from_template_key=profile.created_from_template_key,
        template_version=profile.template_version,
        template_contract_hash=profile.template_contract_hash,
        director_autonomy=profile.director_autonomy,
        selected_genre=profile.selected_genre,
        selected_style_ids=list(profile.selected_style_ids or []),
        selected_skill_ids=list(profile.selected_skill_ids or []),
        selected_shot_language=profile.selected_shot_language,
        asset_slot_requirements=dict(profile.asset_slot_requirements or {}),
        strategy_snapshot=dict(profile.strategy_snapshot or {}),
        version=profile.version,
    )


def _project_read(
    project: Project,
    profile: ProjectCreativeProfile,
) -> ProjectRead:
    return ProjectRead(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        stage=(
            project.stage
            if isinstance(project.stage, ProjectStage)
            else ProjectStage(project.stage)
        ),
        aspect_ratio=project.aspect_ratio,
        target_platform=project.target_platform,
        provider_dispatch_frozen=project.provider_dispatch_frozen,
        version=project.version,
        creative_profile=_profile_read(profile),
    )


async def _profile_for_project(
    session: SessionDep,
    project_id: UUID,
) -> ProjectCreativeProfile:
    profile = await session.scalar(
        select(ProjectCreativeProfile).where(
            ProjectCreativeProfile.project_id == project_id
        )
    )
    if profile is None:
        raise NotFoundError("project creative profile not found")
    return profile


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProjectRead:
    project = await ProjectService(session).create_project(
        workspace_id=body.workspace_id,
        name=body.name,
        aspect_ratio=body.aspect_ratio,
        actor=user,
        target_platform=body.target_platform,
        start_type=body.start_type,
        template_key=body.template_key,
        template_version=body.template_version,
        director_autonomy=body.director_autonomy,
    )
    await session.commit()
    profile = await _profile_for_project(session, project.id)
    return _project_read(project, profile)


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectRead])
async def list_workspace_projects(
    workspace_id: UUID, user: CurrentUser, session: SessionDep
) -> list[ProjectRead]:
    projects = await ProjectService(session).list_projects_for_owner(
        workspace_id=workspace_id, actor=user
    )
    profiles = list(
        (
            await session.execute(
                select(ProjectCreativeProfile).where(
                    ProjectCreativeProfile.project_id.in_(
                        [project.id for project in projects]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    profiles_by_project = {profile.project_id: profile for profile in profiles}
    result: list[ProjectRead] = []
    for project in projects:
        profile = profiles_by_project.get(project.id)
        if profile is None:
            profile = await _profile_for_project(session, project.id)
        result.append(_project_read(project, profile))
    return result


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    profile = await _profile_for_project(session, project.id)
    return _project_read(project, profile)


@router.patch(
    "/projects/{project_id}/creative-profile",
    response_model=ProjectCreativeProfileRead,
)
async def update_project_creative_profile(
    project_id: UUID,
    body: CreativeProfileUpdateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ProjectCreativeProfileRead:
    await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    profile = await session.scalar(
        select(ProjectCreativeProfile)
        .where(ProjectCreativeProfile.project_id == project_id)
        .with_for_update()
    )
    if profile is None:
        raise NotFoundError("project creative profile not found")
    if profile.version != body.expected_version:
        raise ConflictError(
            "creative profile version conflict",
            details={
                "expected_version": body.expected_version,
                "actual_version": profile.version,
            },
        )
    profile.director_autonomy = body.director_autonomy
    profile.version = (profile.version or 1) + 1
    profile.updated_at = datetime.now(UTC)
    await session.commit()
    return _profile_read(profile)
