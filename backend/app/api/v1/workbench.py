"""P1 professional workbench HTTP routes (workspace state + shot design)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, JsonValue

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.api.v1.schemas.workbench import ShotWorkbenchRead
from app.assets.models import Shot
from app.assets.schemas import ShotDirectorState
from app.production.formal_selection import set_formal_keyframe, set_formal_video
from app.production.models import GraphVersion
from app.production.reference_intents import ShotReferenceIntent
from app.production.repair_service import RepairPlanRead, RepairService
from app.production.trace import ExecutionTraceRead, build_execution_trace
from app.production.workbench_execution import (
    WorkbenchExecutionInput,
    WorkbenchExecutionService,
)
from app.shared.errors import ValidationAppError
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


class ExecutionPlanBody(BaseModel):
    stage: Literal["image_keyframe", "video"]
    prompt: str = Field(min_length=1, max_length=20000)
    semantic_intent: dict[str, JsonValue] = Field(default_factory=dict)
    mode_id: str = Field(min_length=1, max_length=120)
    requested_model_id: str | None = None
    requested_binding_id: UUID | None = None
    accept_approximations: bool = False
    references: list[ShotReferenceIntent] = Field(default_factory=list)
    expected_shot_version: int | None = None


class ExecutionPlanRead(BaseModel):
    plan: dict[str, JsonValue]
    plan_fingerprint: str


class ExecutionBody(ExecutionPlanBody):
    plan_fingerprint: str = Field(min_length=64, max_length=64)
    accepted_approximations: list[str] = Field(default_factory=list)


class ExecutionRead(BaseModel):
    node_run_id: UUID
    graph_id: UUID
    graph_version_id: UUID
    status: str
    plan_fingerprint: str


def _execution_input(
    project_id: UUID,
    shot_id: UUID,
    body: ExecutionPlanBody,
) -> WorkbenchExecutionInput:
    return WorkbenchExecutionInput(
        project_id=project_id,
        shot_id=shot_id,
        stage=body.stage,
        prompt=body.prompt,
        semantic_intent=body.semantic_intent,
        mode_id=body.mode_id,
        requested_model_id=body.requested_model_id,
        requested_binding_id=body.requested_binding_id,
        accept_approximations=body.accept_approximations,
        references=body.references,
        expected_shot_version=body.expected_shot_version,
    )


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
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    service = WorkbenchExecutionService(session, user_id=user.id)
    plan = await service.build_plan(
        project=project,
        execution_input=_execution_input(project_id, shot_id, body),
    )
    return ExecutionPlanRead(
        plan=plan.model_dump(mode="json"),
        plan_fingerprint=plan.plan_fingerprint or "",
    )


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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ExecutionRead:
    """Dispatch one shot execution. The server re-validates the plan
    fingerprint / expected shot version / accepted approximations before
    creating the queued NodeRun (03 §37)."""
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    service = WorkbenchExecutionService(session, user_id=user.id)
    # 1) Rebuild the plan from the submitted inputs and re-validate fingerprint.
    rebuilt = await service.build_plan(
        project=project,
        execution_input=_execution_input(project_id, shot_id, body),
    )
    if rebuilt.plan_fingerprint != body.plan_fingerprint:
        raise ValidationAppError(
            "plan fingerprint mismatch: inputs changed since preview",
            details={"code": "PLAN_FINGERPRINT_MISMATCH"},
        )
    # 2) Optimistic shot version check.
    if body.expected_shot_version is not None:
        shot = await session.get(Shot, shot_id)
        if shot is None or shot.project_id != project_id:
            raise ValidationAppError("shot not found", details={"code": "SHOT_NOT_FOUND"})
        if shot.version != body.expected_shot_version:
            raise ValidationAppError(
                "shot changed since plan preview",
                details={"code": "SHOT_VERSION_MISMATCH"},
            )
    # 3) Dispatch (queued NodeRun); Idempotency-Key dedupes retries.
    run = await service.create_and_dispatch(
        project=project,
        execution_input=_execution_input(project_id, shot_id, body),
        idempotency_key_override=idempotency_key,
    )
    await session.commit()
    graph_version = await session.get(GraphVersion, run.graph_version_id)
    graph_id = graph_version.graph_id if graph_version is not None else run.graph_version_id
    return ExecutionRead(
        node_run_id=run.id,
        graph_id=graph_id,
        graph_version_id=run.graph_version_id,
        status=run.status,
        plan_fingerprint=rebuilt.plan_fingerprint or "",
    )



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
    """Mark one keyframe artifact as the shot's formal keyframe (03 §38)."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot = await set_formal_keyframe(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=body.artifact_id,
        expected_shot_version=body.expected_shot_version,
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
    """Mark one video artifact as the shot's formal video (03 §39)."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    shot = await set_formal_video(
        session,
        project_id=project_id,
        shot_id=shot_id,
        artifact_id=body.artifact_id,
        expected_shot_version=body.expected_shot_version,
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



class RepairExecuteBody(BaseModel):
    repair_option: Literal["rerun_video", "regenerate_keyframe_then_video"]
    idempotency_key: str = Field(min_length=1, max_length=160)


class RepairExecuteRead(BaseModel):
    node_run_id: UUID
    status: str
    repair_option: str


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
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    return await RepairService(session).build_repair_plan(
        project=project,
        shot_id=shot_id,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/repair",
    response_model=RepairExecuteRead,
)
async def execute_repair(
    project_id: UUID,
    shot_id: UUID,
    body: RepairExecuteBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> RepairExecuteRead:
    """Execute a V1 repair rerun with an Idempotency-Key (03 §58)."""
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    run = await RepairService(session).execute_repair(
        project=project,
        user=user,
        shot_id=shot_id,
        repair_option=body.repair_option,
        idempotency_key=body.idempotency_key,
    )
    await session.commit()
    return RepairExecuteRead(
        node_run_id=run.id,
        status=run.status,
        repair_option=body.repair_option,
    )
