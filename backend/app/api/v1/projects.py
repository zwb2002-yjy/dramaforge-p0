"""Project HTTP routes (S1.2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.api.v1 import workbench as _workbench
from app.shared.enums import ProjectStage

router = APIRouter(
    tags=["projects"], dependencies=[Depends(require_selected_workspace)]
)

router.include_router(_workbench.router)


class ProjectCreate(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=160)
    aspect_ratio: str = Field(pattern="^(9:16|16:9)$")
    target_platform: str = Field(default="general", max_length=40)


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


def _project_read(project: object) -> ProjectRead:
    return ProjectRead.model_validate(project)


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
    )
    await session.commit()
    return _project_read(project)


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectRead])
async def list_workspace_projects(
    workspace_id: UUID, user: CurrentUser, session: SessionDep
) -> list[ProjectRead]:
    projects = await ProjectService(session).list_projects_for_owner(
        workspace_id=workspace_id, actor=user
    )
    return [_project_read(project) for project in projects]


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    return _project_read(project)
