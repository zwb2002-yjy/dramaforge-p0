"""Read-only projections for BusinessFlow instances, steps and attempts.

These endpoints expose persisted facts only: the acceptance target calls for a
read projection that never advances work, and completion is reported from the
step's own terminal state rather than recomputed or inferred here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.access.models import User
from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SessionDep, require_selected_workspace
from app.director.business_flow_models import (
    DirectorBusinessFlowInstance,
    DirectorBusinessFlowStep,
    DirectorBusinessFlowStepAttempt,
)
from app.director.business_flows import BusinessFlowService
from app.director.master_runs import MasterRunService

router = APIRouter(tags=["business-flows"], dependencies=[Depends(require_selected_workspace)])


class FlowScopeRead(BaseModel):
    type: str
    entity_id: UUID


class BusinessFlowRead(BaseModel):
    id: UUID
    master_run_id: UUID
    plan_id: UUID
    plan_revision: int
    definition_key: str
    definition_version: str
    revision: int
    status: str
    scope: FlowScopeRead
    wait_reason: str | None
    terminal_reason: str | None
    created_at: datetime
    finished_at: datetime | None


class BusinessStepRead(BaseModel):
    id: UUID
    instance_id: UUID
    step_key: str
    revision: int
    status: str
    required: bool
    dependencies: list[str]
    wait_reason: str | None
    completion: dict[str, object]
    result_refs: list[object]


class StepAttemptRead(BaseModel):
    id: UUID
    step_id: UUID
    attempt_no: int
    revision: int
    status: str
    action_kind: str
    node_run_id: UUID | None
    receipt: dict[str, object] | None
    result_refs: list[object]
    unresolved_external: bool
    error_code: str | None


async def _service(project_id: UUID, user: User, session: SessionDep) -> BusinessFlowService:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return BusinessFlowService(session, actor=user, project=project)


def _flow(instance: DirectorBusinessFlowInstance) -> BusinessFlowRead:
    return BusinessFlowRead(
        id=instance.id,
        master_run_id=instance.supervisor_run_id,
        plan_id=instance.plan_id,
        plan_revision=instance.plan_revision,
        definition_key=instance.definition_key,
        definition_version=instance.definition_version,
        revision=instance.revision,
        status=instance.status,
        scope=FlowScopeRead(type=instance.scope_type, entity_id=instance.scope_entity_id),
        wait_reason=instance.wait_reason,
        terminal_reason=instance.terminal_reason,
        created_at=instance.created_at,
        finished_at=instance.finished_at,
    )


def _step(step: DirectorBusinessFlowStep) -> BusinessStepRead:
    raw = dict(step.completion_spec or {})
    dependencies = [str(value) for value in (step.dependencies or [])]
    return BusinessStepRead(
        id=step.id,
        instance_id=step.instance_id,
        step_key=step.step_key,
        revision=step.revision,
        status=step.status,
        required=step.required,
        dependencies=dependencies,
        wait_reason=step.wait_reason,
        completion={
            "rule_id": raw.get("rule_id"),
            "satisfied": step.status == "succeeded",
            "evidence_refs": list(step.result_refs or []),
        },
        result_refs=list(step.result_refs or []),
    )


def _attempt(attempt: DirectorBusinessFlowStepAttempt) -> StepAttemptRead:
    return StepAttemptRead(
        id=attempt.id,
        step_id=attempt.step_id,
        attempt_no=attempt.attempt_no,
        revision=attempt.revision,
        status=attempt.status,
        action_kind=attempt.action_kind,
        node_run_id=attempt.node_run_id,
        receipt=dict(attempt.receipt_ref) if attempt.receipt_ref else None,
        result_refs=list(attempt.result_refs or []),
        unresolved_external=attempt.unresolved_external,
        error_code=attempt.error_code,
    )


@router.get(
    "/projects/{project_id}/director/master-runs/{run_id}/business-flows",
    response_model=list[BusinessFlowRead],
)
async def list_business_flows(
    project_id: UUID, run_id: UUID, user: CurrentUser, session: SessionDep,
) -> list[BusinessFlowRead]:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await MasterRunService(session, actor=user, project=project).get(run_id)
    service = BusinessFlowService(session, actor=user, project=project)
    return [_flow(instance) for instance in await service.list_for_run(run_id)]


@router.get(
    "/projects/{project_id}/director/business-flows/{flow_id}", response_model=BusinessFlowRead,
)
async def read_business_flow(
    project_id: UUID, flow_id: UUID, user: CurrentUser, session: SessionDep,
) -> BusinessFlowRead:
    service = await _service(project_id, user, session)
    return _flow(await service.get(flow_id))


@router.get(
    "/projects/{project_id}/director/business-flows/{flow_id}/steps",
    response_model=list[BusinessStepRead],
)
async def list_business_flow_steps(
    project_id: UUID, flow_id: UUID, user: CurrentUser, session: SessionDep,
) -> list[BusinessStepRead]:
    service = await _service(project_id, user, session)
    await service.get(flow_id)
    return [_step(step) for step in await service.steps(flow_id)]


@router.get(
    "/projects/{project_id}/director/business-flows/{flow_id}/steps/{step_id}/attempts",
    response_model=list[StepAttemptRead],
)
async def list_business_flow_attempts(
    project_id: UUID, flow_id: UUID, step_id: UUID, user: CurrentUser, session: SessionDep,
) -> list[StepAttemptRead]:
    service = await _service(project_id, user, session)
    await service.get(flow_id)
    steps = {step.id: step for step in await service.steps(flow_id)}
    if step_id not in steps:
        from app.shared.errors import NotFoundError

        raise NotFoundError("business flow step not found")
    return [_attempt(attempt) for attempt in await service.attempts(step_id)]


__all__ = ["router"]
