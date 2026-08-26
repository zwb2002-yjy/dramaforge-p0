"""P3-01/P3-03/P3-04 scene summary, workspace snapshot, and structural commands."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.scene_service import SceneStructureService, SceneSummaryService
from app.workbench.scene_service import SceneWorkspaceService

router = APIRouter(tags=["scenes"], dependencies=[Depends(require_selected_workspace)])


class SceneReorderBody(BaseModel):
    new_scene_number: int = Field(ge=1)


class SceneSplitBody(BaseModel):
    at_shot_number: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=160)
    location_name: str | None = Field(default=None, max_length=160)
    time_of_day: str | None = Field(default=None, max_length=40)


class SceneMergeBody(BaseModel):
    target_scene_id: UUID


@router.get("/projects/{project_id}/scenes", response_model=list[dict[str, object]])
async def list_scene_summaries(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[dict[str, object]]:
    return await SceneSummaryService(session).list_summaries(
        project_id=project_id, actor=user
    )


@router.get(
    "/projects/{project_id}/scenes/{scene_id}/workspace",
    response_model=dict[str, object],
)
async def get_scene_workspace(
    project_id: UUID,
    scene_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, object]:
    return await SceneWorkspaceService(session).get_workspace(
        project_id=project_id, scene_id=scene_id, actor=user
    )


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/reorder",
    response_model=dict[str, object],
)
async def reorder_scene(
    project_id: UUID,
    scene_id: UUID,
    body: SceneReorderBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> dict[str, object]:
    scene = await SceneStructureService(session).reorder(
        project_id=project_id,
        scene_id=scene_id,
        actor=user,
        new_scene_number=body.new_scene_number,
    )
    await session.commit()
    return {"id": scene.id, "scene_number": scene.scene_number}


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/copy",
    response_model=dict[str, object],
    status_code=201,
)
async def copy_scene(
    project_id: UUID,
    scene_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> dict[str, object]:
    scene = await SceneStructureService(session).copy(
        project_id=project_id, scene_id=scene_id, actor=user
    )
    await session.commit()
    return {"id": scene.id, "scene_number": scene.scene_number}


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/split-preview",
    response_model=dict[str, object],
)
async def split_scene_preview(
    project_id: UUID,
    scene_id: UUID,
    body: SceneSplitBody,
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, object]:
    return await SceneStructureService(session).split_preview(
        project_id=project_id,
        scene_id=scene_id,
        actor=user,
        at_shot_number=body.at_shot_number,
    )


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/split",
    response_model=dict[str, object],
    status_code=201,
)
async def split_scene(
    project_id: UUID,
    scene_id: UUID,
    body: SceneSplitBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> dict[str, object]:
    scene = await SceneStructureService(session).split(
        project_id=project_id,
        scene_id=scene_id,
        actor=user,
        at_shot_number=body.at_shot_number,
        title=body.title,
        location_name=body.location_name,
        time_of_day=body.time_of_day,
    )
    await session.commit()
    return {"id": scene.id, "scene_number": scene.scene_number}


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/merge-preview",
    response_model=dict[str, object],
)
async def merge_scene_preview(
    project_id: UUID,
    scene_id: UUID,
    body: SceneMergeBody,
    user: CurrentUser,
    session: SessionDep,
) -> dict[str, object]:
    return await SceneStructureService(session).merge_preview(
        project_id=project_id,
        scene_id=scene_id,
        target_scene_id=body.target_scene_id,
        actor=user,
    )


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/merge",
    response_model=dict[str, object],
)
async def merge_scene(
    project_id: UUID,
    scene_id: UUID,
    body: SceneMergeBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> dict[str, object]:
    scene = await SceneStructureService(session).merge(
        project_id=project_id,
        scene_id=scene_id,
        target_scene_id=body.target_scene_id,
        actor=user,
    )
    await session.commit()
    return {"id": scene.id, "scene_number": scene.scene_number}
