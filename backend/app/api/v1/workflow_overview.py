"""Workflow overview API (WF13) — project-wide wire-visible read model.

Read-only aggregation of the existing execution truth.  No new persistence and
no Provider access.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Episode, Scene, Shot
from app.director.workflows.workflow_read_models import (
    build_project_workflow_overview,
)

router = APIRouter(
    tags=["workflow-planning"], dependencies=[Depends(require_selected_workspace)]
)


class WorkflowOverviewResponse(BaseModel):
    overview: dict[str, object]


@router.get(
    "/projects/{project_id}/workflow-overview",
    response_model=WorkflowOverviewResponse,
)
async def get_workflow_overview(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> WorkflowOverviewResponse:
    """Episode → Scene → Shot workflow state + scene production statuses."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    rows = (
        await session.execute(
            select(Episode, Scene)
            .join(Scene, Scene.episode_id == Episode.id)
            .where(Episode.project_id == project_id)
            .order_by(Episode.episode_number, Scene.scene_number)
        )
    ).tuples().all()
    shots = (
        (
            await session.execute(
                select(Shot).where(Shot.project_id == project_id).order_by(Shot.shot_number)
            )
        )
        .scalars()
        .all()
    )
    shots_by_scene: dict[UUID, list[Shot]] = {}
    for shot in shots:
        shots_by_scene.setdefault(shot.scene_id, []).append(shot)
    overview = build_project_workflow_overview(
        project_id=project_id,
        scenes=list(rows),
        shots_by_scene=shots_by_scene,
    )
    return WorkflowOverviewResponse(overview=overview.model_dump(mode="json"))
