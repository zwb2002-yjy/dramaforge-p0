"""Read-only model diagnostics; never an alternative generation endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.contracts.production_commands import ExecutionPlanBody
from app.production.model_inspection import (
    GenerationCompileRead,
    GenerationSnapshotRead,
    ModelInspectionService,
    ModelQueryRead,
    Stage,
)
from app.production.workbench_execution import WorkbenchExecutionInput
from app.providers.model_profiles.slots import ModelSlot

router = APIRouter(tags=["model-inspection"], dependencies=[Depends(require_selected_workspace)])


@router.get("/projects/{project_id}/model-capabilities", response_model=ModelQueryRead)
async def get_model_capabilities(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    model_id: str | None = None,
    stage: Stage | None = None,
    slot: ModelSlot | None = None,
    mode_id: str | None = None,
) -> ModelQueryRead:
    return await ModelInspectionService(session, actor=user).get_model_capabilities(
        project_id=project_id,
        model_id=model_id,
        stage=stage,
        slot=slot,
        mode_id=mode_id,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/compile-preview",
    response_model=GenerationCompileRead,
)
async def preview_generation_compile(
    project_id: UUID,
    shot_id: UUID,
    body: ExecutionPlanBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> GenerationCompileRead:
    return await ModelInspectionService(session, actor=user).preview_generation_compile(
        project_id=project_id,
        request=WorkbenchExecutionInput(
            project_id=project_id,
            shot_id=shot_id,
            **body.model_dump(),
        ),
    )


@router.get(
    "/projects/{project_id}/shots/{shot_id}/generations/{run_id}/snapshot",
    response_model=GenerationSnapshotRead,
)
async def get_generation_snapshot(
    project_id: UUID,
    shot_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> GenerationSnapshotRead:
    return await ModelInspectionService(session, actor=user).get_generation_snapshot(
        project_id=project_id,
        shot_id=shot_id,
        run_id=run_id,
    )
