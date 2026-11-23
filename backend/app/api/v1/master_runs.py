"""Read confirmed goals and record the owner's explicit, revision-bound controls."""

from contextlib import suppress
from datetime import datetime
from functools import partial
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.contracts.delivery_verification import DeliveryPackage, ProjectDeliveryGoal
from app.director.business_flows import series_export_flow
from app.director.master_run_models import DirectorMasterRun, DirectorMasterRunPlan
from app.director.master_runs import MasterRunService
from app.director.proposal_models import DirectorProposalItem
from app.production.series_delivery import verify_bound_exports, verify_delivery_target

router = APIRouter(
    prefix="/projects/{project_id}/director/master-runs",
    tags=["master-runs"],
    dependencies=[Depends(require_selected_workspace)],
)


class CompletionCheck(BaseModel):
    model_config = ConfigDict(extra="allow")
    rule_id: str
    satisfied: bool
    reason_code: str | None = None
    missing_episode_ranges: list[tuple[int, int]] = Field(default_factory=list)
    evidence_refs: list[DeliveryPackage] = Field(default_factory=list)


class VerificationRead(BaseModel):
    model_config = ConfigDict(extra="allow")
    satisfied: bool
    checks: list[CompletionCheck]


class RunRead(BaseModel):
    id: UUID
    project_id: UUID
    source_thread_id: UUID
    origin_turn_id: UUID
    goal: str
    status: str
    desired_state: str
    revision: int
    control_epoch: int
    current_plan_id: UUID | None
    current_plan_revision: int | None
    wait_reason: str | None
    deadline_at: datetime | None
    finished_at: datetime | None
    archived_at: datetime | None
    progress: dict[str, int]
    unresolved_external_count: int
    available_actions: list[str]
    last_verification: VerificationRead | None = None


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: UUID
    master_run_id: UUID
    revision: int
    schema_version: str
    plan_hash: str
    decision_ref: UUID
    created_at: datetime
    plan_data: dict[str, object]
    proposal_id: UUID
    decision_status: str
    delivery_check: ProjectDeliveryGoal | None = None


async def _plan_read(plan: DirectorMasterRunPlan, session: SessionDep) -> PlanRead:
    item = await session.get(DirectorProposalItem, plan.decision_ref)
    assert item is not None
    data = plan.plan_data
    rules = data.get("completion")
    check = None
    if (
        isinstance(rules, list)
        and len(rules) == 1
        and isinstance(rules[0], dict)
        and rules[0].get("rule_id") == "project_delivery_ready_v1"
        and data.get("limits")
        == {"max_model_calls": 0, "max_tool_calls": 0, "max_provider_calls": 0}
    ):
        with suppress(ValidationError):
            candidate = ProjectDeliveryGoal.model_validate(rules[0])
            expected_flows = (
                [series_export_flow(plan.project_id, candidate.planned_episode_count)]
                if candidate.output_slot and candidate.planned_episode_count
                else []
            )
            if data.get("flows") == expected_flows:
                check = candidate
    return PlanRead.model_validate(
        {
            **{
                key: getattr(plan, key)
                for key in PlanRead.model_fields
                if key not in {"proposal_id", "decision_status", "delivery_check"}
            },
            "proposal_id": item.proposal_id,
            "decision_status": item.status,
            "delivery_check": check,
        }
    )


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(default="", max_length=1000)


class ControlReceipt(BaseModel):
    master_run_id: UUID
    operation: str
    expected_revision: int
    result_revision: int
    status: str
    desired_state: str
    control_epoch: int
    unresolved_external_count: int | None
    verification: VerificationRead | None = None
    reason: str | None = None


async def _service(project_id: UUID, user: CurrentUser, session: SessionDep) -> MasterRunService:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return MasterRunService(session, actor=user, project=project)


Service = Annotated[MasterRunService, Depends(_service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def _run_read(service: MasterRunService, run: DirectorMasterRun) -> RunRead:
    plan = await service.current_plan(run)
    actions = {
        "planning": ["pause", "cancel"],
        "waiting": ["pause", "cancel"],
        "running": ["pause", "cancel"],
        "paused": ["resume", "cancel"],
    }.get(run.status, [])
    if run.status == "waiting" and run.desired_state == "run" and plan:
        actions.append("verify")
    return RunRead.model_validate(
        {
            **{
                key: getattr(run, key)
                for key in (
                    "id",
                    "project_id",
                    "source_thread_id",
                    "origin_turn_id",
                    "goal",
                    "status",
                    "desired_state",
                    "revision",
                    "control_epoch",
                    "current_plan_id",
                    "wait_reason",
                    "deadline_at",
                    "finished_at",
                    "archived_at",
                )
            },
            **await service.summary(run),
            "current_plan_revision": plan.revision if plan else None,
            "available_actions": actions,
            "last_verification": await service.last_verification(run),
        }
    )


class RunPage(BaseModel):
    items: list[RunRead]
    next_offset: int | None


@router.get("", response_model=RunPage)
async def list_goals(
    service: Service,
    status: str | None = None,
    include_archived: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> RunPage:
    rows = await service.list_runs(
        status=status, include_archived=include_archived, limit=limit, offset=offset
    )
    more = len(rows) == limit and bool(
        await service.list_runs(
            status=status,
            include_archived=include_archived,
            limit=1,
            offset=offset + limit,
        )
    )
    return RunPage(
        items=[await _run_read(service, row) for row in rows],
        next_offset=offset + limit if more else None,
    )


@router.get("/{run_id}", response_model=RunRead)
async def read_goal(run_id: UUID, service: Service) -> RunRead:
    return await _run_read(service, await service.get(run_id))


@router.get("/{run_id}/plans", response_model=list[PlanRead])
async def list_plans(
    run_id: UUID, service: Service, session: SessionDep, limit: Limit = 50, offset: Offset = 0
) -> list[PlanRead]:
    return [
        await _plan_read(p, session)
        for p in await service.list_plans(
            run_id,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("/{run_id}/plans/{plan_id}", response_model=PlanRead)
async def read_plan(run_id: UUID, plan_id: UUID, service: Service, session: SessionDep) -> PlanRead:
    return await _plan_read(await service.get_plan(run_id, plan_id), session)


async def _control(
    operation: Literal["pause", "resume", "cancel", "verify"],
    run_id: UUID,
    body: ControlRequest,
    service: MasterRunService,
    session: SessionDep,
) -> ControlReceipt:
    result = await service.control(
        run_id=run_id,
        operation=operation,
        expected_revision=body.expected_revision,
        reason=body.reason,
        delivery_verifier=partial(verify_delivery_target, session),
        slot_verifier=partial(verify_bound_exports, session),
    )
    receipt = ControlReceipt.model_validate(result)
    await session.commit()
    return receipt


@router.post("/{run_id}/verify")
async def verify(
    run_id: UUID, body: ControlRequest, service: Service, session: SessionDep, _: CsrfDep
) -> ControlReceipt:
    return await _control("verify", run_id, body, service, session)


@router.post("/{run_id}/pause")
async def pause(
    run_id: UUID, body: ControlRequest, service: Service, session: SessionDep, _: CsrfDep
) -> ControlReceipt:
    return await _control("pause", run_id, body, service, session)


@router.post("/{run_id}/resume")
async def resume(
    run_id: UUID, body: ControlRequest, service: Service, session: SessionDep, _: CsrfDep
) -> ControlReceipt:
    return await _control("resume", run_id, body, service, session)


@router.post("/{run_id}/cancel")
async def cancel(
    run_id: UUID, body: ControlRequest, service: Service, session: SessionDep, _: CsrfDep
) -> ControlReceipt:
    return await _control("cancel", run_id, body, service, session)


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    archived: bool = Field(strict=True)


@router.patch("/{run_id}")
async def archive(
    run_id: UUID, body: ArchiveRequest, service: Service, session: SessionDep, _: CsrfDep
) -> RunRead:
    run = await service.archive(
        run_id=run_id, expected_revision=body.expected_revision, archived=body.archived
    )
    result = await _run_read(service, run)
    await session.commit()
    return result
