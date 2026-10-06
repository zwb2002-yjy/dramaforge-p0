"""Per-shot workflow state read model (WF13).

Exposes the shot's frozen workflow template / participation state and the
deterministic multi-character capability assessment for planning visibility.

Freezing that state is a domain action owned by the Director / Workbench, so
this module is read-only: there is no HTTP write surface for it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.access.models import Project
from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Episode, Scene, Shot
from app.director.workflows.workflow_read_models import (
    ShotWorkflowState,
    build_shot_workflow_state,
)
from app.shared.errors import NotFoundError

router = APIRouter(
    tags=["workflow-planning"], dependencies=[Depends(require_selected_workspace)]
)


class ShotWorkflowStateResponse(BaseModel):
    workflow_state: ShotWorkflowState


async def _shot_with_episode(
    session: SessionDep, *, project_id: UUID, shot_id: UUID, actor_user: CurrentUser
) -> tuple[Shot, UUID]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=actor_user)
    row = (
        await session.execute(
            select(Shot, Episode)
            .join(Scene, Scene.id == Shot.scene_id)
            .join(Episode, Episode.id == Scene.episode_id)
            .where(Shot.id == shot_id, Shot.project_id == project_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("shot not found")
    shot, episode = row
    return shot, episode.id


@router.get(
    "/projects/{project_id}/shots/{shot_id}/workflow-state",
    response_model=ShotWorkflowStateResponse,
)
async def get_shot_workflow_state(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ShotWorkflowStateResponse:
    """Wire-visible workflow state for one shot (read-only aggregation).

    Resolves the workspace keyframe manifest so ``capability_assessment`` is a
    deterministic read (mirrors the domain planning freeze), letting the UI
    surface EXACT / APPROXIMATE / UNSUPPORTED honestly without a provider call.
    """
    from app.providers.manifest import ModelManifest
    from app.providers.workspace_router import resolve_workspace_bridge

    shot, episode_id = await _shot_with_episode(
        session, project_id=project_id, shot_id=shot_id, actor_user=user
    )
    project = await session.get(Project, project_id)
    assert project is not None
    assessment_manifest: ModelManifest | None = None
    try:
        bridge = await resolve_workspace_bridge(
            session,
            workspace_id=project.workspace_id,
            provider_type="agnes",
            media_kind="image",
        )
        if isinstance(bridge.manifest, ModelManifest):
            assessment_manifest = bridge.manifest
    except Exception:  # noqa: BLE001 - a read model must never fail a page
        assessment_manifest = None
    state = build_shot_workflow_state(
        shot=shot,
        episode_id=episode_id,
        assessment_manifest=assessment_manifest,
    )
    return ShotWorkflowStateResponse(workflow_state=state)
