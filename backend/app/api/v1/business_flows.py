"""Read-only projections for BusinessFlow instances, steps and attempts.

These endpoints expose persisted facts only: the acceptance target calls for a
read projection that never advances work, and completion is reported from the
step's own terminal state rather than recomputed or inferred here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ValidationError
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import User
from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import AssetVersion
from app.assets.research_models import ResearchResultRevision
from app.contracts.production_commands import ExecutionReceipt
from app.delivery.models import Export
from app.director.business_flow_models import (
    DirectorBusinessFlowInstance,
    DirectorBusinessFlowStep,
    DirectorBusinessFlowStepAttempt,
)
from app.director.business_flows import BusinessFlowService
from app.director.master_runs import MasterRunService
from app.director.proposal_models import DirectorProposal
from app.execution.models import Artifact, NodeRun
from app.production.models import GraphVersion, ProductionGraph
from app.shared.errors import NotFoundError

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


class PublicResultRef(BaseModel):
    kind: str
    id: UUID
    display_name: str


class FlowCompletionRead(BaseModel):
    rule_id: str | None
    satisfied: bool
    evidence_refs: list[PublicResultRef]


class BusinessStepRead(BaseModel):
    id: UUID
    instance_id: UUID
    step_key: str
    revision: int
    status: str
    required: bool
    dependencies: list[str]
    wait_reason: str | None
    completion: FlowCompletionRead
    result_refs: list[PublicResultRef]


class StepAttemptRead(BaseModel):
    id: UUID
    step_id: UUID
    attempt_no: int
    revision: int
    status: str
    action_kind: str
    node_run_id: UUID | None
    receipt: ExecutionReceipt | None
    result_refs: list[PublicResultRef]
    unresolved_external: bool
    error_code: str | None


class BusinessFlowPage(BaseModel):
    items: list[BusinessFlowRead]
    total: int
    next_offset: int | None


class BusinessStepPage(BaseModel):
    items: list[BusinessStepRead]
    total: int
    next_offset: int | None


class StepAttemptPage(BaseModel):
    items: list[StepAttemptRead]
    total: int
    next_offset: int | None


Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def _page[T](
    session: AsyncSession, query: Select[tuple[T]], limit: int, offset: int
) -> tuple[list[T], int, int | None]:
    total = int(
        await session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    )
    rows = list(await session.scalars(query.offset(offset).limit(limit)))
    return rows, total, offset + len(rows) if rows and offset + len(rows) < total else None


_RESULT_TYPES = {
    "proposal": (DirectorProposal.id, DirectorProposal.project_id, "导演提案"),
    "story_proposal": (DirectorProposal.id, DirectorProposal.project_id, "剧本提案"),
    "artifact": (Artifact.id, Artifact.project_id, "产物"),
    "asset_version": (AssetVersion.id, AssetVersion.project_id, "素材版本"),
    "node_run": (NodeRun.id, NodeRun.project_id, "执行任务"),
    "execution_receipt": (NodeRun.id, NodeRun.project_id, "执行回执"),
    "research_revision": (ResearchResultRevision.id, ResearchResultRevision.project_id, "研究修订"),
    "export": (Export.id, Export.project_id, "导出"),
}


def _ref(raw: object) -> PublicResultRef | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
        return None
    kind = raw["kind"]
    if kind not in _RESULT_TYPES:
        return None
    try:
        identity = UUID(str(raw.get("id")))
    except ValueError:
        return None
    return PublicResultRef(
        kind=kind, id=identity, display_name=f"{_RESULT_TYPES[kind][2]} · {str(identity)[:8]}"
    )


async def _visible(
    session: AsyncSession, project_id: UUID, rows: Iterable[list[object]]
) -> set[tuple[str, UUID]]:
    ids: dict[str, set[UUID]] = defaultdict(set)
    for values in rows:
        for value in values:
            if ref := _ref(value):
                ids[ref.kind].add(ref.id)
    allowed: set[tuple[str, UUID]] = set()
    for kind, (identity, owner, _) in _RESULT_TYPES.items():
        if ids.get(kind):
            found = await session.scalars(
                select(identity).where(owner == project_id, identity.in_(ids[kind]))
            )
            allowed.update((kind, i) for i in found)
    return allowed


def _refs(values: list[object], allowed: set[tuple[str, UUID]]) -> list[PublicResultRef]:
    return [r for value in values if (r := _ref(value)) and (r.kind, r.id) in allowed]


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


def _step(step: DirectorBusinessFlowStep, allowed: set[tuple[str, UUID]]) -> BusinessStepRead:
    raw = dict(step.completion_spec or {})
    dependencies = [str(value) for value in (step.dependencies or [])]
    rule = raw.get("rule_id")
    return BusinessStepRead(
        id=step.id,
        instance_id=step.instance_id,
        step_key=step.step_key,
        revision=step.revision,
        status=step.status,
        required=step.required,
        dependencies=dependencies,
        wait_reason=step.wait_reason,
        completion=FlowCompletionRead(
            rule_id=rule if isinstance(rule, str) else None,
            satisfied=step.status == "succeeded",
            evidence_refs=_refs(step.result_refs or [], allowed),
        ),
        result_refs=_refs(step.result_refs or [], allowed),
    )


def _attempt(
    attempt: DirectorBusinessFlowStepAttempt,
    allowed: set[tuple[str, UUID]],
    runs: dict[UUID, tuple[UUID, UUID]],
) -> StepAttemptRead:
    receipt = None
    if attempt.node_run_id in runs and isinstance(attempt.receipt_ref, dict):
        try:
            parsed = ExecutionReceipt.model_validate(
                {k: attempt.receipt_ref[k] for k in ExecutionReceipt.model_fields}
            )
            if (
                parsed.node_run_id == attempt.node_run_id
                and (parsed.graph_id, parsed.graph_version_id) == runs[parsed.node_run_id]
                and re.fullmatch(r"[0-9a-f]{64}", parsed.plan_fingerprint)
                and parsed.status
                in {
                    "queued",
                    "running",
                    "completed",
                    "cached",
                    "failed",
                    "cancelled",
                    "cancel_requested",
                    "completed_after_cancel",
                }
            ):
                receipt = parsed
        except (KeyError, ValidationError):
            pass
    return StepAttemptRead(
        id=attempt.id,
        step_id=attempt.step_id,
        attempt_no=attempt.attempt_no,
        revision=attempt.revision,
        status=attempt.status,
        action_kind=attempt.action_kind,
        node_run_id=attempt.node_run_id if attempt.node_run_id in runs else None,
        receipt=receipt,
        result_refs=_refs(attempt.result_refs or [], allowed),
        unresolved_external=attempt.unresolved_external,
        error_code=(
            attempt.error_code
            if not attempt.error_code
            or re.fullmatch(r"(?:Tool[A-Za-z]{2,60}|[A-Z][A-Z0-9_]{1,79})", attempt.error_code)
            else "ACTION_FAILED"
        ),
    )


@router.get(
    "/projects/{project_id}/director/master-runs/{run_id}/business-flows",
    response_model=BusinessFlowPage,
)
async def list_business_flows(
    project_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> BusinessFlowPage:
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await MasterRunService(session, actor=user, project=project).get(run_id)
    f = DirectorBusinessFlowInstance
    rows, total, nxt = await _page(
        session,
        select(f)
        .where(f.project_id == project_id, f.supervisor_run_id == run_id)
        .order_by(f.created_at, f.id),
        limit,
        offset,
    )
    return BusinessFlowPage(items=[_flow(row) for row in rows], total=total, next_offset=nxt)


@router.get(
    "/projects/{project_id}/director/business-flows/{flow_id}",
    response_model=BusinessFlowRead,
)
async def read_business_flow(
    project_id: UUID,
    flow_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> BusinessFlowRead:
    service = await _service(project_id, user, session)
    return _flow(await service.get(flow_id))


@router.get(
    "/projects/{project_id}/director/business-flows/{flow_id}/steps",
    response_model=BusinessStepPage,
)
async def list_business_flow_steps(
    project_id: UUID,
    flow_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> BusinessStepPage:
    service = await _service(project_id, user, session)
    await service.get(flow_id)
    step = DirectorBusinessFlowStep
    rows, total, nxt = await _page(
        session,
        select(step)
        .where(step.project_id == project_id, step.instance_id == flow_id)
        .order_by(step.step_key, step.id),
        limit,
        offset,
    )
    allowed = await _visible(session, project_id, (row.result_refs for row in rows))
    return BusinessStepPage(
        items=[_step(row, allowed) for row in rows], total=total, next_offset=nxt
    )


@router.get(
    "/projects/{project_id}/director/business-flows/{flow_id}/steps/{step_id}/attempts",
    response_model=StepAttemptPage,
)
async def list_business_flow_attempts(
    project_id: UUID,
    flow_id: UUID,
    step_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> StepAttemptPage:
    service = await _service(project_id, user, session)
    await service.get(flow_id)
    if (
        await session.scalar(
            select(DirectorBusinessFlowStep.id).where(
                DirectorBusinessFlowStep.id == step_id,
                DirectorBusinessFlowStep.instance_id == flow_id,
                DirectorBusinessFlowStep.project_id == project_id,
            )
        )
        is None
    ):
        raise NotFoundError("business flow step not found")
    attempt = DirectorBusinessFlowStepAttempt
    rows, total, nxt = await _page(
        session,
        select(attempt)
        .where(
            attempt.project_id == project_id,
            attempt.instance_id == flow_id,
            attempt.step_id == step_id,
        )
        .order_by(attempt.attempt_no, attempt.id),
        limit,
        offset,
    )
    allowed = await _visible(session, project_id, (row.result_refs for row in rows))
    runs = {
        r[0]: (r[1], r[2])
        for r in await session.execute(
            select(NodeRun.id, GraphVersion.graph_id, GraphVersion.id)
            .join(GraphVersion, GraphVersion.id == NodeRun.graph_version_id)
            .join(ProductionGraph, ProductionGraph.id == GraphVersion.graph_id)
            .where(
                NodeRun.project_id == project_id,
                ProductionGraph.project_id == project_id,
                NodeRun.id.in_([row.node_run_id for row in rows if row.node_run_id]),
            )
        )
    }
    return StepAttemptPage(
        items=[_attempt(row, allowed, runs) for row in rows], total=total, next_offset=nxt
    )


__all__ = ["router"]
