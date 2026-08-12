"""Creation experience routes (start_project, brief, plan, materialize)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.creation.service import CreationService
from app.director.legacy_guard import require_legacy_execution_allowed
from app.shared.enums import ExperienceMode

router = APIRouter(
    tags=["creation"], dependencies=[Depends(require_selected_workspace)]
)


class StartProjectRequest(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=160)
    aspect_ratio: str = Field(pattern="^(9:16|16:9)$")
    experience_mode: ExperienceMode = ExperienceMode.QUICK
    idea: str = ""


class StartProjectResponse(BaseModel):
    project_id: UUID
    experience_mode: ExperienceMode
    brief_id: UUID
    brief_revision_id: UUID
    event_id: UUID
    outbox_id: UUID
    text_provider_operations: int


class BriefUpdateRequest(BaseModel):
    logline: str = Field(min_length=1, max_length=2000)
    tone: str = ""
    audience: str = ""


class BriefRevisionResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    brief: dict[str, Any]
    content_hash: str


class CreationStateBriefResponse(BriefRevisionResponse):
    source: str


class CreationStatePlanResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    plan: dict[str, Any]
    context_hash: str
    source: str
    materialized: bool


class CreationStateResponse(BaseModel):
    brief: CreationStateBriefResponse | None
    plan: CreationStatePlanResponse | None


class PlanRequest(BaseModel):
    brief_revision_id: UUID
    plan: dict[str, Any] = Field(default_factory=dict)


class PlanResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    context_hash: str


class ConfirmPlanRequest(BaseModel):
    materialization_ops: list[str] = Field(
        default_factory=lambda: ["create_shot_stub", "enqueue_keyframe"]
    )


class ConfirmPlanResponse(BaseModel):
    plan_id: UUID
    graph_id: UUID
    graph_version_id: UUID
    node_run_id: UUID
    graph_ids: list[UUID]
    graph_version_ids: list[UUID]
    node_run_ids: list[UUID]
    shot_ids: list[UUID]
    materialization_ops: list[str]


@router.post(
    "/creation/start-project",
    response_model=StartProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_project(
    body: StartProjectRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> StartProjectResponse:
    result = await CreationService(session).start_project(
        workspace_id=body.workspace_id,
        name=body.name,
        aspect_ratio=body.aspect_ratio,
        actor=user,
        experience_mode=body.experience_mode,
        idea=body.idea,
    )
    return StartProjectResponse(
        project_id=result.project_id,
        experience_mode=ExperienceMode(result.experience_mode),
        brief_id=result.brief_id,
        brief_revision_id=result.brief_revision_id,
        event_id=result.event_id,
        outbox_id=result.outbox_id,
        text_provider_operations=result.text_provider_operations,
    )


@router.get(
    "/projects/{project_id}/creation-state",
    response_model=CreationStateResponse,
)
async def get_creation_state(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> CreationStateResponse:
    result = await CreationService(session).get_creation_state(
        project_id=project_id,
        actor=user,
    )
    revision = result.brief_revision
    plan = result.plan
    return CreationStateResponse(
        brief=(
            CreationStateBriefResponse(
                id=revision.id,
                project_id=revision.project_id,
                status=revision.status,
                brief=dict(revision.brief),
                content_hash=revision.content_hash,
                source=revision.source_kind,
            )
            if revision is not None
            else None
        ),
        plan=(
            CreationStatePlanResponse(
                id=plan.id,
                project_id=plan.project_id,
                status=plan.status,
                plan=dict(plan.plan),
                context_hash=plan.context_hash,
                source="agent" if plan.source_agent_run_id is not None else "manual",
                materialized=plan.materialized_at is not None,
            )
            if plan is not None
            else None
        ),
    )


@router.post(
    "/projects/{project_id}/brief",
    response_model=BriefRevisionResponse,
)
async def update_brief(
    project_id: UUID,
    body: BriefUpdateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> BriefRevisionResponse:
    rev = await CreationService(session).update_brief_manual(
        project_id=project_id,
        actor=user,
        logline=body.logline,
        tone=body.tone,
        audience=body.audience,
    )
    return BriefRevisionResponse(
        id=rev.id,
        project_id=rev.project_id,
        status=rev.status,
        brief=dict(rev.brief),
        content_hash=rev.content_hash,
    )


@router.post(
    "/projects/{project_id}/brief/{revision_id}/confirm",
    response_model=BriefRevisionResponse,
)
async def confirm_brief(
    project_id: UUID,
    revision_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> BriefRevisionResponse:
    rev = await CreationService(session).confirm_brief(
        project_id=project_id, revision_id=revision_id, actor=user
    )
    return BriefRevisionResponse(
        id=rev.id,
        project_id=rev.project_id,
        status=rev.status,
        brief=dict(rev.brief),
        content_hash=rev.content_hash,
    )


@router.post("/projects/{project_id}/plans", response_model=PlanResponse)
async def create_plan(
    project_id: UUID,
    body: PlanRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> PlanResponse:
    plan = await CreationService(session).create_or_update_plan_manual(
        project_id=project_id,
        actor=user,
        brief_revision_id=body.brief_revision_id,
        plan_body=body.plan or {"prompt": "opening keyframe"},
    )
    return PlanResponse(
        id=plan.id,
        project_id=plan.project_id,
        status=plan.status,
        context_hash=plan.context_hash,
    )


@router.post(
    "/projects/{project_id}/plans/{plan_id}/confirm",
    response_model=ConfirmPlanResponse,
)
async def confirm_plan(
    project_id: UUID,
    plan_id: UUID,
    body: ConfirmPlanRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ConfirmPlanResponse:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await require_legacy_execution_allowed(
        session, project_id=project_id, action="legacy_confirm_plan_media"
    )
    result = await CreationService(session).confirm_plan_and_materialize(
        project_id=project_id,
        plan_id=plan_id,
        actor=user,
        materialization_ops=body.materialization_ops,
    )
    return ConfirmPlanResponse(
        plan_id=result.plan_id,
        graph_id=result.graph_id,
        graph_version_id=result.graph_version_id,
        node_run_id=result.node_run_id,
        graph_ids=result.graph_ids,
        graph_version_ids=result.graph_version_ids,
        node_run_ids=result.node_run_ids,
        shot_ids=result.shot_ids,
        materialization_ops=result.materialization_ops,
    )


class AgentGenerateRequest(BaseModel):
    """User fee/planning authorization gate for Agent text calls."""

    idea: str = ""
    authorize: bool = True
    brief_revision_id: UUID | None = None


class AgentBriefResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    brief: dict[str, Any]
    content_hash: str
    source: str = "agent"


class AgentPlanResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    plan: dict[str, Any]
    context_hash: str
    source: str = "agent"


@router.post(
    "/projects/{project_id}/brief/generate",
    response_model=AgentBriefResponse,
)
async def generate_brief_agent(
    project_id: UUID,
    body: AgentGenerateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> AgentBriefResponse:
    """Agent Brief draft (BYOK text LLM). Manual path remains POST /brief."""
    rev = await CreationService(session).generate_brief_agent(
        project_id=project_id,
        actor=user,
        idea=body.idea,
        authorize=body.authorize,
    )
    return AgentBriefResponse(
        id=rev.id,
        project_id=rev.project_id,
        status=rev.status,
        brief=dict(rev.brief),
        content_hash=rev.content_hash,
        source="agent",
    )


@router.post(
    "/projects/{project_id}/plans/generate",
    response_model=AgentPlanResponse,
)
async def generate_plan_agent(
    project_id: UUID,
    body: AgentGenerateRequest,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> AgentPlanResponse:
    """Agent Plan draft after confirmed Brief. Manual path remains POST /plans."""
    if body.brief_revision_id is None:
        from app.shared.errors import ValidationAppError

        raise ValidationAppError("brief_revision_id required")
    plan = await CreationService(session).generate_plan_agent(
        project_id=project_id,
        actor=user,
        brief_revision_id=body.brief_revision_id,
        authorize=body.authorize,
    )
    return AgentPlanResponse(
        id=plan.id,
        project_id=plan.project_id,
        status=plan.status,
        plan=dict(plan.plan),
        context_hash=plan.context_hash,
        source="agent",
    )
