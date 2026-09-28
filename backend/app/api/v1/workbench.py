"""P1 professional workbench HTTP routes (workspace state + shot design)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.api.v1.schemas.workbench import ShotWorkbenchRead
from app.assets.schemas import ShotDirectorState
from app.assets.voice import VoiceOptionsRead
from app.contracts.domain_events import FormalSelected
from app.contracts.production_commands import ExecutionBody, ExecutionPlanBody
from app.execution.models import NodeRun
from app.production.application.commands import (
    ProductionCommands,
    execution_receipt,
)
from app.production.application.commands import (
    execution_input as _execution_input,
)
from app.production.application.events import append_production_notice
from app.production.execution_plan import WorkbenchExecutionPlan
from app.production.formal_selection import set_formal_keyframe, set_formal_video
from app.production.repair_service import (
    RepairPlanRead,
    RepairRequestRead,
    RepairService,
    RepairStepPlanRead,
    record_repair_adoption,
)
from app.production.trace import ExecutionTraceRead, build_execution_trace
from app.production.workbench_execution import (
    WorkbenchExecutionService,
)
from app.providers.voice_config import voice_options
from app.shared.errors import NotFoundError
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


@router.get("/projects/{project_id}/voice-options", response_model=VoiceOptionsRead)
async def get_voice_options(
    project_id: UUID, user: CurrentUser, session: SessionDep
) -> VoiceOptionsRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return voice_options()


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
    response_model=ShotWorkbenchRead,
)
async def get_shot_workbench(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ShotWorkbenchRead:
    workbench = await ShotWorkbenchService(session).get_workbench(
        project_id=project_id, shot_id=shot_id, actor=user
    )
    return ShotWorkbenchRead.model_validate(workbench)


# ---------------------------------------------------------------------------
# P4-07 New Execution API: execution-plan preview + executions dispatch.
# ---------------------------------------------------------------------------


class ExecutionPlanRead(BaseModel):
    plan: WorkbenchExecutionPlan
    plan_fingerprint: str


class ExecutionRead(BaseModel):
    director_turn_id: UUID | None = None
    node_run_id: UUID
    graph_id: UUID
    graph_version_id: UUID
    status: str
    plan_fingerprint: str


@router.post(
    "/projects/{project_id}/shots/{shot_id}/execution-plan",
    response_model=ExecutionPlanRead,
)
async def create_execution_plan(
    project_id: UUID,
    shot_id: UUID,
    body: ExecutionPlanBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ExecutionPlanRead:
    """Preview a frozen execution plan. Never calls a Provider."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    service = WorkbenchExecutionService(session, user_id=user.id)
    plan = await service.build_plan(
        project=project,
        execution_input=_execution_input(project_id, shot_id, body),
        allow_unaccepted_approximations=True,
    )
    return ExecutionPlanRead(
        plan=plan,
        plan_fingerprint=plan.plan_fingerprint or "",
    )


async def _execution_read(session: SessionDep, run: NodeRun) -> ExecutionRead:
    receipt = await execution_receipt(session, run)
    return ExecutionRead(**receipt.model_dump())


@router.get(
    "/projects/{project_id}/shots/{shot_id}/executions/receipt",
    response_model=ExecutionRead,
)
async def get_execution_receipt(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    stage: Literal["image_keyframe", "video"],
    idempotency_key: str = Query(min_length=1, max_length=2000),
) -> ExecutionRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    run = await WorkbenchExecutionService(session, user_id=user.id).find_command_receipt(
        project_id=project_id,
        shot_id=shot_id,
        stage=stage,
        command_key=idempotency_key,
    )
    if run is None:
        raise NotFoundError("Execution command has no committed receipt")
    return await _execution_read(session, run)


@router.post(
    "/projects/{project_id}/shots/{shot_id}/executions",
    response_model=ExecutionRead,
)
async def create_execution(
    project_id: UUID,
    shot_id: UUID,
    body: ExecutionBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=2000,
    ),
) -> ExecutionRead:
    """Dispatch one shot execution. The server re-validates the plan
    fingerprint / expected shot version / accepted approximations before
    creating the queued NodeRun (03 §37)."""
    receipt = await ProductionCommands(session).submit_user_execution(
        actor=user,
        project_id=project_id,
        shot_id=shot_id,
        body=body,
        command_key=idempotency_key,
    )
    await session.commit()
    return ExecutionRead(**receipt.model_dump())


class FormalKeyframeBody(BaseModel):
    artifact_id: UUID
    expected_shot_version: int | None = None


class FormalKeyframeRead(BaseModel):
    shot_id: UUID
    formal_keyframe_artifact_id: UUID
    version: int


@router.post(
    "/projects/{project_id}/shots/{shot_id}/formal-keyframe",
    response_model=FormalKeyframeRead,
)
async def set_shot_formal_keyframe(
    project_id: UUID,
    shot_id: UUID,
    body: FormalKeyframeBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> FormalKeyframeRead:
    """Mark one keyframe artifact as the shot's formal keyframe (03 §38).

    The product entry point enforces human review admission: a candidate may
    only become Formal once a stored human decision approves that exact Artifact.
    """
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot = await set_formal_keyframe(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=body.artifact_id,
        expected_shot_version=body.expected_shot_version,
        require_review_approval=True,
    )
    await append_production_notice(
        session,
        project_id=project.id,
        actor_id=user.id,
        notice=FormalSelected(
            shot_id=shot_id,
            shot_version=shot.version,
            artifact_id=body.artifact_id,
            stage="image_keyframe",
        ),
    )
    # If a repair produced this candidate, record that the user adopted it.
    await record_repair_adoption(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=body.artifact_id,
    )
    await session.commit()
    assert shot.formal_keyframe_artifact_id is not None
    return FormalKeyframeRead(
        shot_id=shot.id,
        formal_keyframe_artifact_id=shot.formal_keyframe_artifact_id,
        version=shot.version,
    )


class FormalVideoBody(BaseModel):
    artifact_id: UUID
    expected_shot_version: int | None = None


class FormalVideoRead(BaseModel):
    shot_id: UUID
    formal_video_artifact_id: UUID
    version: int


@router.post(
    "/projects/{project_id}/shots/{shot_id}/formal-video",
    response_model=FormalVideoRead,
)
async def set_shot_formal_video(
    project_id: UUID,
    shot_id: UUID,
    body: FormalVideoBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> FormalVideoRead:
    """Mark one video artifact as the shot's formal video (03 §39).

    Same admission rule as the keyframe entry point: the human decision must be
    about this exact Artifact.
    """
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot = await set_formal_video(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=body.artifact_id,
        expected_shot_version=body.expected_shot_version,
        require_review_approval=True,
    )
    await append_production_notice(
        session,
        project_id=project.id,
        actor_id=user.id,
        notice=FormalSelected(
            shot_id=shot_id, shot_version=shot.version, artifact_id=body.artifact_id, stage="video"
        ),
    )
    await record_repair_adoption(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=body.artifact_id,
    )
    await session.commit()
    assert shot.formal_video_artifact_id is not None
    return FormalVideoRead(
        shot_id=shot.id,
        formal_video_artifact_id=shot.formal_video_artifact_id,
        version=shot.version,
    )


@router.get(
    "/projects/{project_id}/runs/{run_id}/trace",
    response_model=ExecutionTraceRead,
)
async def get_execution_trace(
    project_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ExecutionTraceRead:
    """Structured execution trace for one NodeRun (03 §40)."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await build_execution_trace(
        session,
        project_id=project_id,
        run_id=run_id,
    )


class RepairExecuteRead(BaseModel):
    node_run_id: UUID
    status: str
    repair_option: str
    repair_id: UUID | None = None
    step_ordinal: int | None = None
    next_action: str | None = None


class RepairCreateBody(BaseModel):
    repair_option: Literal["rerun_video", "regenerate_keyframe_then_video"]
    plan_hash: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=160)


class RepairStepPlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accept_approximations: bool = False


class RepairStepExecuteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_plan_fingerprint: str = Field(min_length=64, max_length=64)
    expected_step_ordinal: int = Field(ge=1, le=4)
    accept_approximations: bool = False
    idempotency_key: str = Field(min_length=1, max_length=160)


class RepairCloseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["completed", "abandoned"]


@router.post(
    "/projects/{project_id}/shots/{shot_id}/repair-plan",
    response_model=RepairPlanRead,
)
async def get_repair_plan(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> RepairPlanRead:
    """Compute a repair plan from open annotations (03 §57)."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await RepairService(session).build_repair_plan(
        project=project,
        shot_id=shot_id,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/repairs",
    response_model=RepairRequestRead,
    status_code=201,
)
async def create_repair(
    project_id: UUID,
    shot_id: UUID,
    body: RepairCreateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> RepairRequestRead:
    """Persist a confirmed repair intent against the previewed plan hash."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    service = RepairService(session)
    request = await service.create_repair(
        project=project,
        user=user,
        shot_id=shot_id,
        option=body.repair_option,
        plan_hash=body.plan_hash,
        request_key=body.idempotency_key,
    )
    state = await service.read_repair(project=project, shot_id=shot_id, repair_id=request.id)
    await session.commit()
    return state


@router.get(
    "/projects/{project_id}/shots/{shot_id}/repairs",
    response_model=list[RepairRequestRead],
)
async def list_repairs(
    project_id: UUID,
    shot_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[RepairRequestRead]:
    """Repairs that can be resumed after reopening the page."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await RepairService(session).list_repairs(project=project, shot_id=shot_id)


@router.get(
    "/projects/{project_id}/shots/{shot_id}/repairs/{repair_id}",
    response_model=RepairRequestRead,
)
async def read_repair(
    project_id: UUID,
    shot_id: UUID,
    repair_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> RepairRequestRead:
    """One repair with its stored steps and the next action."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await RepairService(session).read_repair(
        project=project, shot_id=shot_id, repair_id=repair_id
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/repairs/{repair_id}/steps",
    response_model=RepairExecuteRead,
)
async def execute_repair_step(
    project_id: UUID,
    shot_id: UUID,
    repair_id: UUID,
    body: RepairStepExecuteBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> RepairExecuteRead:
    """Dispatch the next confirmed step; review steps are refused here."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    service = RepairService(session)
    request, step, run = await service.execute_step(
        project=project,
        user=user,
        shot_id=shot_id,
        repair_id=repair_id,
        expected_plan_fingerprint=body.expected_plan_fingerprint,
        expected_step_ordinal=body.expected_step_ordinal,
        accept_approximations=body.accept_approximations,
        idempotency_key=body.idempotency_key,
    )
    # Read before committing: the repair tables are RLS-scoped per transaction,
    # so a post-commit read starts a fresh scope and finds nothing.
    state = await service.read_repair(project=project, shot_id=shot_id, repair_id=request.id)
    await session.commit()
    return RepairExecuteRead(
        node_run_id=run.id,
        status=run.status,
        repair_option=request.option,
        repair_id=request.id,
        step_ordinal=step.ordinal,
        next_action=state.next_action,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/repairs/{repair_id}/step-plan",
    response_model=RepairStepPlanRead,
)
async def preview_repair_step(
    project_id: UUID, shot_id: UUID, repair_id: UUID,
    user: CurrentUser, session: SessionDep,
    body: RepairStepPlanBody | None = None,
) -> RepairStepPlanRead:
    """Read-only media plan preview; no provider submission or queued run."""
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await RepairService(session).build_step_plan(
        project=project, user=user, shot_id=shot_id, repair_id=repair_id,
        accept_approximations=body.accept_approximations if body else False,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/repairs/{repair_id}/close",
    response_model=RepairRequestRead,
)
async def close_repair(
    project_id: UUID, shot_id: UUID, repair_id: UUID, body: RepairCloseBody,
    user: CurrentUser, session: SessionDep, _csrf: CsrfDep,
) -> RepairRequestRead:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    state = await RepairService(session).close_repair(
        project=project, shot_id=shot_id, repair_id=repair_id, reason=body.reason,
    )
    await session.commit()
    return state
