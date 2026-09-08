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

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.director.next_action import DirectorNextActionRead, DirectorNextActionService
from app.director.recommendation import (
    DirectorRecommendation,
    DirectorRecommendationRequest,
    DirectorRecommendationService,
)
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
    request_summary: dict[str, object]
    response_summary: dict[str, object]
    token_usage: dict[str, object]
    reported_cost: str | None
    cost_status: str
    currency: str
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
            request_summary=dict(turn.request_summary or {}),
            response_summary=dict(turn.response_summary or {}),
            token_usage=dict(turn.token_usage or {}),
            reported_cost=(str(turn.provider_cost) if turn.provider_cost is not None else None),
            cost_status=turn.cost_status,
            currency=turn.currency,
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
    "/projects/{project_id}/director/turns/{turn_id}/decision",
    response_model=DirectorTurnRead,
)
async def decide_director_turn(
    project_id: UUID, turn_id: UUID, body: DirectorTurnDecisionBody,
    user: CurrentUser, session: SessionDep, _csrf: CsrfDep,
) -> DirectorTurnRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
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
