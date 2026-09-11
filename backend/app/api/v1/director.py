"""Proposal-only Director Assistant endpoints.

The retired controlled workflow, budget, trial, batch, repair, and export
commands intentionally have no HTTP compatibility layer. Media execution is
owned by the canonical Scene/Shot Workbench APIs; this router exposes bounded
proposal-only text turns and never mutates Shot design or Formal media.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.config import get_settings
from app.contracts.director_runtime import ResumeSignal, RuntimeScope, StopRequest
from app.contracts.production_commands import ExecutionBody
from app.director.next_action import DirectorNextActionRead, DirectorNextActionService
from app.director.recommendation import (
    DirectorRecommendation,
    DirectorRecommendationRequest,
    DirectorRecommendationService,
)
from app.director.runtime.control import DirectorRuntimeControlService
from app.director.runtime.delegation import DirectorRuntimeDelegationService
from app.director.runtime.routing import DirectorEngineRouter
from app.director.runtime.start import DirectorRuntimeStartService
from app.director.runtime.wakeups import DirectorRuntimeWakeupService
from app.director.suggestion import (
    ShotDirectorSuggestion,
    ShotDirectorSuggestionRequest,
    ShotDirectorSuggestionService,
)
from app.director.turn_models import DirectorTurn
from app.director.turn_service import DirectorTurnService
from app.shared.errors import ConflictError, ValidationAppError

router = APIRouter(tags=["director"], dependencies=[Depends(require_selected_workspace)])


class DirectorTurnRead(BaseModel):
    """Secret-free durable Director coordination state."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    workspace_id: UUID
    actor_id: UUID
    scope_type: str
    scope_entity_id: UUID
    request_key: str
    context_hash: str
    input_versions: dict[str, object]
    intent_snapshot: dict[str, object]
    model_resolution: dict[str, object]
    transport_record_id: str | None
    transport_status: str
    engine_version: str | None
    state_schema_version: str | None
    runtime_execution_id: UUID | None
    runtime_revision: int | None
    request_summary: dict[str, object]
    response_summary: dict[str, object]
    token_usage: dict[str, object]
    reported_cost: str | None
    cost_status: str
    currency: str
    schema_repair_count: int
    output_hash: str | None
    output_snapshot: dict[str, object]
    status: str
    wait_reason: str | None
    revision: int
    proposal_id: UUID | None
    dispatched_command_key: str | None
    node_run_ids: list[object]
    step_count: int
    deadline: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, turn: DirectorTurn) -> DirectorTurnRead:
        return cls(
            id=turn.id,
            project_id=turn.project_id,
            workspace_id=turn.workspace_id,
            actor_id=turn.actor_id,
            scope_type=turn.scope_type,
            scope_entity_id=turn.scope_entity_id,
            request_key=turn.request_key,
            context_hash=turn.context_hash,
            input_versions=dict(turn.input_versions or {}),
            intent_snapshot=dict(turn.intent_snapshot or {}),
            model_resolution=dict(turn.model_resolution or {}),
            transport_record_id=turn.transport_record_id,
            transport_status=turn.transport_status,
            engine_version=turn.engine_version,
            state_schema_version=turn.state_schema_version,
            runtime_execution_id=turn.runtime_execution_id,
            runtime_revision=turn.runtime_revision,
            request_summary=dict(turn.request_summary or {}),
            response_summary=dict(turn.response_summary or {}),
            token_usage=dict(turn.token_usage or {}),
            reported_cost=(str(turn.provider_cost) if turn.provider_cost is not None else None),
            cost_status=turn.cost_status,
            currency=turn.currency,
            schema_repair_count=turn.schema_repair_count,
            output_hash=turn.output_hash,
            output_snapshot=dict(turn.output_snapshot or {}),
            status=turn.status,
            wait_reason=turn.wait_reason,
            revision=turn.revision,
            proposal_id=turn.proposal_id,
            dispatched_command_key=turn.dispatched_command_key,
            node_run_ids=list(turn.node_run_ids or []),
            step_count=turn.step_count,
            deadline=turn.deadline,
            last_error=turn.last_error,
            created_at=turn.created_at,
            updated_at=turn.updated_at,
        )


class DirectorTurnStopBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class DirectorTurnResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    event_key: str = Field(min_length=1, max_length=200)


class DirectorTurnDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    decision: Literal["accept", "reject"]
    accepted_operation_indices: list[StrictInt] = Field(default_factory=list, max_length=20)


class DirectorRuntimeStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    authorization_ref: UUID | None = None
    request_key: str = Field(min_length=1, max_length=200)
    max_steps: int = Field(default=6, ge=1, le=8)


class DirectorRuntimeResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: UUID
    reference_id: UUID
    expected_runtime_revision: int = Field(ge=1)


class DirectorRuntimeDecisionBody(DirectorTurnDecisionBody):
    signal_id: UUID
    expected_runtime_revision: int = Field(ge=1)


class DirectorRuntimeStopBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_runtime_revision: int | None = Field(default=None, ge=1)
    expected_turn_revision: int = Field(ge=1)


class DirectorRuntimeDelegationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    execution: ExecutionBody
    authorization_expires_at: datetime
    max_steps: int = Field(default=6, ge=3, le=8)


@router.post(
    "/projects/{project_id}/director/shots/{shot_id}/suggestion",
    response_model=ShotDirectorSuggestion,
)
async def suggest_shot_design(
    project_id: UUID,
    shot_id: UUID,
    body: ShotDirectorSuggestionRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ShotDirectorSuggestion:
    """Return one validated suggestion with durable text-call evidence."""

    if body.shot_id != shot_id:
        raise ValidationAppError(
            "shot id in the request body does not match the route",
            details={"code": "SHOT_SUGGESTION_SCOPE_MISMATCH"},
        )
    return await ShotDirectorSuggestionService(session).suggest(
        project_id=project_id,
        actor=user,
        request=body,
    )


@router.post(
    "/projects/{project_id}/shots/{shot_id}/recommendation",
    response_model=DirectorRecommendation,
)
async def recommend_shot_design(
    project_id: UUID,
    shot_id: UUID,
    body: DirectorRecommendationRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> DirectorRecommendation:
    if body.shot_id != shot_id:
        raise ValidationAppError(
            "shot id in the request body does not match the route",
            details={"code": "RECOMMENDATION_SCOPE_MISMATCH"},
        )
    return await DirectorRecommendationService(session).recommend(
        project_id=project_id,
        actor=user,
        request=body,
    )


@router.get(
    "/projects/{project_id}/director/turns",
    response_model=list[DirectorTurnRead],
)
async def list_director_turns(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    scope_type: str | None = Query(default=None, max_length=24),
    scope_entity_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[DirectorTurnRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    turns = await DirectorTurnService(session).list(
        project_id=project_id,
        scope_type=scope_type,
        scope_entity_id=scope_entity_id,
        limit=limit,
    )
    return [DirectorTurnRead.from_model(turn) for turn in turns]


@router.post(
    "/projects/{project_id}/director/runtime/turns",
    response_model=DirectorTurnRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_director_runtime_turn(
    project_id: UUID,
    body: DirectorRuntimeStartBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorTurnRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user,
    )
    turn, _wakeup = await DirectorRuntimeStartService(
        session, settings=get_settings(),
    ).accept(
        project=project,
        actor=user,
        proposal_id=body.proposal_id,
        authorization_ref=body.authorization_ref,
        request_key=body.request_key,
        max_steps=body.max_steps,
    )
    await session.refresh(turn)
    result = DirectorTurnRead.from_model(turn)
    await session.commit()
    return result


@router.post(
    "/projects/{project_id}/director/runtime/shots/{shot_id}/executions",
    response_model=DirectorTurnRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delegate_shot_execution_to_director(
    project_id: UUID,
    shot_id: UUID,
    body: DirectorRuntimeDelegationBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorTurnRead:
    """Authorize one frozen plan; the Director stops again at the next gate."""

    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user,
    )
    turn, _wakeup = await DirectorRuntimeDelegationService(
        session, settings=get_settings(),
    ).accept(
        project=project,
        actor=user,
        shot_id=shot_id,
        decision_id=body.decision_id,
        execution=body.execution,
        authorization_expires_at=body.authorization_expires_at,
        max_steps=body.max_steps,
    )
    await session.refresh(turn)
    result = DirectorTurnRead.from_model(turn)
    await session.commit()
    return result


@router.get(
    "/projects/{project_id}/director/turns/{turn_id}",
    response_model=DirectorTurnRead,
)
async def get_director_turn(
    project_id: UUID,
    turn_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> DirectorTurnRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    turn = await DirectorTurnService(session).get(project_id=project_id, turn_id=turn_id)
    return DirectorTurnRead.from_model(turn)


@router.post(
    "/projects/{project_id}/director/turns/{turn_id}/stop",
    response_model=DirectorTurnRead,
)
async def stop_director_turn(
    project_id: UUID,
    turn_id: UUID,
    body: DirectorTurnStopBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorTurnRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    existing = await DirectorTurnService(session).get(
        project_id=project_id, turn_id=turn_id,
    )
    if existing.runtime_execution_id is not None:
        raise ConflictError(
            "Use the versioned runtime stop endpoint for this turn",
            details={"code": "DIRECTOR_RUNTIME_ENDPOINT_REQUIRED"},
        )
    turn = await DirectorTurnService(session).stop(
        project_id=project_id,
        turn_id=turn_id,
        expected_revision=body.expected_revision,
    )
    await session.commit()
    return DirectorTurnRead.from_model(turn)


@router.post(
    "/projects/{project_id}/director/turns/{turn_id}/resume",
    response_model=DirectorNextActionRead,
)
async def resume_director_turn(
    project_id: UUID,
    turn_id: UUID,
    body: DirectorTurnResumeBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorNextActionRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id,
        actor=user,
    )
    existing = await DirectorTurnService(session).get(
        project_id=project_id, turn_id=turn_id,
    )
    if existing.runtime_execution_id is not None:
        raise ConflictError(
            "Use the versioned runtime resume endpoint for this turn",
            details={"code": "DIRECTOR_RUNTIME_ENDPOINT_REQUIRED"},
        )
    try:
        result = await DirectorNextActionService(session).reconcile(
            project=project,
            turn_id=turn_id,
            event_key=body.event_key,
            expected_revision=body.expected_revision,
        )
    except ConflictError as exc:
        if exc.details.get("code") == "DIRECTOR_TURN_LIMIT_REACHED":
            await session.commit()
        raise
    await session.commit()
    return result


@router.post(
    "/projects/{project_id}/director/runtime/turns/{turn_id}/resume",
    response_model=DirectorTurnRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_director_runtime_turn(
    project_id: UUID,
    turn_id: UUID,
    body: DirectorRuntimeResumeBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorTurnRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user,
    )
    turn = await DirectorTurnService(session).get(
        project_id=project_id, turn_id=turn_id,
    )
    DirectorEngineRouter.engine_for(turn)
    if turn.runtime_execution_id is None or turn.runtime_revision is None:
        raise ConflictError(
            "Director runtime has not reached a resumable checkpoint",
            details={"code": "DIRECTOR_RUNTIME_NOT_RESUMABLE"},
        )
    runtime_execution_id = turn.runtime_execution_id
    if turn.runtime_revision != body.expected_runtime_revision:
        raise ConflictError(
            "Director runtime revision changed",
            details={
                "code": "DIRECTOR_RUNTIME_REVISION_CONFLICT",
                "revision": turn.runtime_revision,
            },
        )
    signal = ResumeSignal(
        scope=RuntimeScope(
            workspace_id=project.workspace_id,
            project_id=project.id,
            actor_id=user.id,
        ),
        turn_id=turn.id,
        signal_id=body.signal_id,
        reason="user_decision",
        reference_id=body.reference_id,
        expected_revision=body.expected_runtime_revision,
    )
    await DirectorRuntimeWakeupService(session).enqueue_resume(
        signal, runtime_execution_id=runtime_execution_id,
    )
    await session.commit()
    return DirectorTurnRead.from_model(turn)


@router.post(
    "/projects/{project_id}/director/runtime/turns/{turn_id}/decision",
    response_model=DirectorTurnRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def decide_director_runtime_turn(
    project_id: UUID,
    turn_id: UUID,
    body: DirectorRuntimeDecisionBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorTurnRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user,
    )
    turns = DirectorTurnService(session)
    turn = await turns.get(project_id=project_id, turn_id=turn_id)
    DirectorEngineRouter.engine_for(turn)
    if turn.proposal_id is not None:
        raise ConflictError(
            "Use the canonical Proposal decision API for this turn",
            details={"code": "DIRECTOR_PROPOSAL_DECISION_REQUIRED"},
        )
    if turn.runtime_execution_id is None or turn.runtime_revision is None:
        raise ConflictError(
            "Director runtime has not reached a decision checkpoint",
            details={"code": "DIRECTOR_RUNTIME_NOT_RESUMABLE"},
        )
    runtime_execution_id = turn.runtime_execution_id
    if turn.runtime_revision != body.expected_runtime_revision:
        raise ConflictError(
            "Director runtime revision changed",
            details={
                "code": "DIRECTOR_RUNTIME_REVISION_CONFLICT",
                "revision": turn.runtime_revision,
            },
        )
    turn = await turns.record_user_decision(
        project_id=project.id,
        turn_id=turn.id,
        expected_revision=body.expected_revision,
        decision=body.decision,
        accepted_operation_indices=body.accepted_operation_indices,
    )
    signal = ResumeSignal(
        scope=RuntimeScope(
            workspace_id=project.workspace_id,
            project_id=project.id,
            actor_id=user.id,
        ),
        turn_id=turn.id,
        signal_id=body.signal_id,
        reason="user_decision",
        reference_id=turn.id,
        expected_revision=body.expected_runtime_revision,
    )
    await DirectorRuntimeWakeupService(session).enqueue_resume(
        signal, runtime_execution_id=runtime_execution_id,
    )
    await session.commit()
    return DirectorTurnRead.from_model(turn)


@router.post(
    "/projects/{project_id}/director/runtime/turns/{turn_id}/stop",
    response_model=DirectorTurnRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def stop_director_runtime_turn(
    project_id: UUID,
    turn_id: UUID,
    body: DirectorRuntimeStopBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> DirectorTurnRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user,
    )
    turns = DirectorTurnService(session)
    turn = await turns.get(project_id=project_id, turn_id=turn_id)
    DirectorEngineRouter.engine_for(turn)
    if turn.runtime_execution_id is None:
        raise ConflictError(
            "Director runtime is not bound",
            details={"code": "DIRECTOR_RUNTIME_NOT_BOUND"},
        )
    if turn.runtime_revision != body.expected_runtime_revision:
        raise ConflictError(
            "Director runtime revision changed",
            details={
                "code": "DIRECTOR_RUNTIME_REVISION_CONFLICT",
                "revision": turn.runtime_revision,
            },
        )
    request = StopRequest(
        scope=RuntimeScope(
            workspace_id=project.workspace_id,
            project_id=project.id,
            actor_id=user.id,
        ),
        turn_id=turn.id,
        request_id=body.request_id,
        # A newly accepted Turn is stoppable before its first checkpoint.
        # Revision 1 is the graph's initial state if the start wakeup won the race.
        expected_revision=body.expected_runtime_revision or 1,
    )
    await DirectorRuntimeControlService(session).request_stop(
        project_id=project.id,
        runtime_execution_id=turn.runtime_execution_id,
    )
    await DirectorRuntimeWakeupService(session).enqueue_stop(
        request, runtime_execution_id=turn.runtime_execution_id,
    )
    turn = await turns.stop(
        project_id=project.id,
        turn_id=turn.id,
        expected_revision=body.expected_turn_revision,
    )
    await session.commit()
    return DirectorTurnRead.from_model(turn)


@router.post(
    "/projects/{project_id}/director/turns/{turn_id}/decision",
    response_model=DirectorTurnRead,
)
async def decide_director_turn(
    project_id: UUID, turn_id: UUID, body: DirectorTurnDecisionBody,
    user: CurrentUser, session: SessionDep, _csrf: CsrfDep,
) -> DirectorTurnRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    existing = await DirectorTurnService(session).get(
        project_id=project_id, turn_id=turn_id,
    )
    if existing.runtime_execution_id is not None:
        raise ConflictError(
            "Use the versioned runtime resume endpoint for this turn",
            details={"code": "DIRECTOR_RUNTIME_ENDPOINT_REQUIRED"},
        )
    try:
        turn = await DirectorTurnService(session).record_user_decision(
            project_id=project_id, turn_id=turn_id, expected_revision=body.expected_revision,
            decision=body.decision, accepted_operation_indices=body.accepted_operation_indices,
        )
    except ConflictError as exc:
        if exc.details.get("code") == "DIRECTOR_TURN_LIMIT_REACHED":
            await session.commit()
        raise
    await session.commit()
    return DirectorTurnRead.from_model(turn)


__all__ = ["router", "suggest_shot_design"]
