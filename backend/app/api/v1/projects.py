"""Project HTTP routes (S1.2)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.shared.enums import ExperienceMode, ProjectStage

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=160)
    aspect_ratio: str = Field(pattern="^(9:16|16:9)$")
    budget_limit: Decimal = Field(default=Decimal("0"), ge=0)
    budget_currency: str = Field(default="USD", min_length=3, max_length=3)
    target_platform: str = Field(default="general", max_length=40)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    stage: ProjectStage
    aspect_ratio: str
    target_platform: str
    budget_limit: Decimal
    budget_currency: str
    provider_dispatch_frozen: bool
    version: int


class ExperienceModeUpdate(BaseModel):
    experience_mode: ExperienceMode


class PreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    project_id: UUID
    experience_mode: ExperienceMode
    last_guided_step: str | None


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ProjectRead:
    project = await ProjectService(session).create_project(
        organization_id=body.organization_id,
        name=body.name,
        aspect_ratio=body.aspect_ratio,
        actor=user,
        budget_limit=body.budget_limit,
        budget_currency=body.budget_currency,
        target_platform=body.target_platform,
    )
    await session.commit()
    return ProjectRead(
        id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        stage=ProjectStage(project.stage),
        aspect_ratio=project.aspect_ratio,
        target_platform=project.target_platform,
        budget_limit=project.budget_limit,
        budget_currency=project.budget_currency,
        provider_dispatch_frozen=project.provider_dispatch_frozen,
        version=project.version,
    )


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectRead:
    project = await ProjectService(session).get_project_for_member(
        project_id=project_id, actor=user
    )
    return ProjectRead(
        id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        stage=ProjectStage(project.stage),
        aspect_ratio=project.aspect_ratio,
        target_platform=project.target_platform,
        budget_limit=project.budget_limit,
        budget_currency=project.budget_currency,
        provider_dispatch_frozen=project.provider_dispatch_frozen,
        version=project.version,
    )


@router.put(
    "/projects/{project_id}/preferences/experience-mode",
    response_model=PreferenceRead,
)
async def set_experience_mode(
    project_id: UUID,
    body: ExperienceModeUpdate,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> PreferenceRead:
    pref = await ProjectService(session).set_experience_mode(
        project_id=project_id, actor=user, mode=body.experience_mode
    )
    await session.commit()
    return PreferenceRead(
        user_id=pref.user_id,
        project_id=pref.project_id,
        experience_mode=ExperienceMode(pref.experience_mode),
        last_guided_step=pref.last_guided_step,
    )
