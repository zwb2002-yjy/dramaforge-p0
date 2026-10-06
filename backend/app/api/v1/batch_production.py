"""HTTP boundary for explicit batch production commands and read models."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.production.application.batch_production import (
    BatchProductionDispatchBody,
    BatchProductionDispatchRead,
    BatchProductionPreviewRead,
    ProductionTodoQueueRead,
)
from app.production.application.batch_production import (
    dispatch_batch_production as dispatch_batch_production_service,
)
from app.production.application.batch_production import (
    preview_batch_production as preview_batch_production_service,
)
from app.production.application.batch_production import (
    read_production_todos as read_production_todos_service,
)
from app.production.workbench_execution import PlanStage

router = APIRouter(tags=["production"], dependencies=[Depends(require_selected_workspace)])


@router.get(
    "/projects/{project_id}/batch-production/preview",
    response_model=BatchProductionPreviewRead,
)
async def preview_batch_production(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    stage: PlanStage,
    scene_id: UUID | None = None,
) -> BatchProductionPreviewRead:
    return await preview_batch_production_service(
        project_id=project_id,
        user=user,
        session=session,
        stage=stage,
        scene_id=scene_id,
    )


@router.get(
    "/projects/{project_id}/production-todos",
    response_model=ProductionTodoQueueRead,
)
async def read_production_todos(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProductionTodoQueueRead:
    return await read_production_todos_service(
        project_id=project_id,
        user=user,
        session=session,
    )


@router.post(
    "/projects/{project_id}/batch-production",
    response_model=BatchProductionDispatchRead,
)
async def dispatch_batch_production(
    project_id: UUID,
    body: BatchProductionDispatchBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> BatchProductionDispatchRead:
    return await dispatch_batch_production_service(
        project_id=project_id,
        body=body,
        user=user,
        session=session,
    )
