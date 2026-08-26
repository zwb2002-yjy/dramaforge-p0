"""P1 professional workbench HTTP routes (workspace state + shot design)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.schemas import ShotDirectorState
from app.workbench.scene_service import ShotWorkbenchService
from app.workbench.shot_service import ShotDesignService
from app.workbench.workspace_state_service import WorkspaceStateService

router = APIRouter(tags=["workbench"], dependencies=[Depends(require_selected_workspace)])


class WorkspaceStateRead(BaseModel):
    state: dict[str, object]


class WorkspaceStateUpdate(BaseModel):
    state: dict[str, object] = Field(default_factory=dict)


class ShotDesignUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    director_state: ShotDirectorState | None = None
    image_prompt: str | None = Field(default=None, max_length=20000)
    video_prompt: str | None = Field(default=None, max_length=20000)


class ShotDesignRead(BaseModel):
    id: UUID
    project_id: UUID
    scene_id: UUID
    shot_number: int
    version: int
    director_state: dict[str, object]
    image_prompt: str
    video_prompt: str
    updated_at: datetime


@router.get("/projects/{project_id}/workspace-state", response_model=WorkspaceStateRead)
async def get_workspace_state(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> WorkspaceStateRead:
    state = await WorkspaceStateService(session).get_workspace_state(
        project_id=project_id, actor=user
    )
    return WorkspaceStateRead(state=state)


@router.patch("/projects/{project_id}/workspace-state", response_model=WorkspaceStateRead)
async def update_workspace_state(
    project_id: UUID,
    body: WorkspaceStateUpdate,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> WorkspaceStateRead:
    state = await WorkspaceStateService(session).update_workspace_state(
        project_id=project_id, actor=user, state=dict(body.state)
    )
    await session.commit()
    return WorkspaceStateRead(state=state)


@router.patch(
    "/projects/{project_id}/shots/{shot_id}/design",
    response_model=ShotDesignRead,
)
async def update_shot_design(
    project_id: UUID,
    shot_id: UUID,
    body: ShotDesignUpdate,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ShotDesignRead:
    shot = await ShotDesignService(session).update_shot_design(
        project_id=project_id,
        shot_id=shot_id,
        actor=user,
        expected_version=body.expected_version,
        director_state=(
            body.director_state.model_dump() if body.director_state is not None else None
        ),
        image_prompt=body.image_prompt,
        video_prompt=body.video_prompt,
    )
    await session.commit()
    return ShotDesignRead(
        id=shot.id,
        project_id=shot.project_id,
        scene_id=shot.scene_id,
        shot_number=shot.shot_number,
        version=shot.version,
        director_state=dict(shot.director_state or {}),
        image_prompt=shot.image_prompt,
        video_prompt=shot.video_prompt,
        updated_at=shot.updated_at,
    )


@router.get(
    "/projects/{project_id}/shots/{shot_id}/workbench",
    response_model=dict[str, object],
)
async def get_shot_workbench(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, object]:
    return await ShotWorkbenchService(session).get_workbench(
        project_id=project_id, shot_id=shot_id, actor=user
    )