"""Formal and experimental branch API for the professional workspace."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.access.models import Project
from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.assets.models import Shot
from app.execution.branches import experiment_id as run_experiment_id
from app.execution.models import Artifact, GraphNode, NodeRun
from app.execution.shot_review import start_shot_nodes
from app.production.experiment_service import (
    ExperimentCreateInput,
    ExperimentService,
)
from app.production.models import ExperimentBranch
from app.providers.catalog_models import ModelCatalogEntry
from app.providers.models import ProviderConnection, ProviderModelBinding
from app.runtime.scheduler import NodeRunScheduler
from app.shared.errors import ConflictError, NotFoundError, ValidationAppError

router = APIRouter(tags=["experiments"], dependencies=[Depends(require_selected_workspace)])

_DONE = frozenset({"completed", "cached", "completed_after_cancel"})
_TARGET_PURPOSE = {"keyframe": "keyframe", "video": "video"}
_DOWNSTREAM_AFTER_KEYFRAME = [
    "identity_review",
    "video",
    "video_drift_review",
    "composite",
    "continuity_review",
]


class ExperimentCreateBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    branch_type: str = Field(default="model_experiment", max_length=32)
    source_shot_id: UUID | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, object] = Field(default_factory=dict)
    selected_model: str | None = None


class ExperimentRead(BaseModel):
    id: UUID
    project_id: UUID
    source_shot_id: UUID | None
    name: str
    branch_type: str
    status: str
    source_artifact_ids: list[str]
    candidate_artifact_ids: list[str]
    comparison: dict[str, object]
    adopted_shot_ids: list[str]
    parameters: dict[str, object]
    selected_model: str | None
    created_at: datetime
    decided_at: datetime | None


class ExperimentStartBody(BaseModel):
    target_node_key: Literal["keyframe", "video"] = "video"


class ExperimentStartRead(BaseModel):
    experiment: ExperimentRead
    run_ids: list[UUID]
    job_ids: list[str]


class ExperimentDecisionBody(BaseModel):
    decision: Literal["accepted", "rejected", "kept"]
    adoption_scope: Literal[
        "current_node",
        "keyframe_keep_video",
        "keyframe_rerun_downstream",
    ] | None = None
    candidate_artifact_id: UUID | None = None
    adopted_shot_ids: list[UUID] = Field(default_factory=list)


def _read(
    row: ExperimentBranch,
    *,
    candidate_artifact_ids: list[str] | None = None,
    comparison: dict[str, object] | None = None,
) -> ExperimentRead:
    return ExperimentRead(
        id=row.id,
        project_id=row.project_id,
        source_shot_id=row.source_shot_id,
        name=row.name,
        branch_type=row.branch_type,
        status=row.status,
        source_artifact_ids=list(row.source_artifact_ids),
        candidate_artifact_ids=(
            list(row.candidate_artifact_ids)
            if candidate_artifact_ids is None
            else candidate_artifact_ids
        ),
        comparison=dict(row.comparison) if comparison is None else comparison,
        adopted_shot_ids=list(row.adopted_shot_ids),
        parameters=dict(row.parameters),
        selected_model=row.selected_model,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


def _parameter_run_ids(row: ExperimentBranch) -> list[UUID]:
    raw = (row.parameters or {}).get("run_ids")
    if not isinstance(raw, list):
        return []
    result: list[UUID] = []
    for value in raw:
        try:
            result.append(UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return result


async def _artifact_summary(session: SessionDep, artifact_id: UUID) -> dict[str, object]:
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        return {"artifact_id": str(artifact_id), "missing": True}
    return {
        "artifact_id": str(artifact.id),
        "artifact_type": artifact.artifact_type,
        "mime_type": artifact.mime_type,
        "content_hash": artifact.content_hash,
        "width": artifact.width,
        "height": artifact.height,
        "duration_seconds": (
            str(artifact.duration_seconds) if artifact.duration_seconds is not None else None
        ),
    }


async def _candidate_state(
    session: SessionDep,
    row: ExperimentBranch,
) -> tuple[list[str], dict[str, object], list[NodeRun]]:
    run_ids = _parameter_run_ids(row)
    runs = (
        list(
            (
                await session.execute(
                    select(NodeRun).where(
                        NodeRun.project_id == row.project_id,
                        NodeRun.id.in_(run_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        if run_ids
        else []
    )
    runs = [
        run
        for run in runs
        if run_experiment_id(run.input_snapshot) == str(row.id)
    ]
    runs.sort(key=lambda item: (item.attempt_no, item.created_at, str(item.id)))
    candidate_ids = [
        str(run.result_artifact_id)
        for run in runs
        if run.status in _DONE and run.result_artifact_id is not None
    ]
    candidate_ids = list(dict.fromkeys(candidate_ids))
    formal = [
        await _artifact_summary(session, UUID(value))
        for value in row.source_artifact_ids
        if value
    ]
    candidates = [await _artifact_summary(session, UUID(value)) for value in candidate_ids]
    run_states = [
        {
            "run_id": str(run.id),
            "node_key": str((run.input_snapshot or {}).get("node_key") or ""),
            "status": run.status,
            "artifact_id": (
                str(run.result_artifact_id) if run.result_artifact_id is not None else None
            ),
            "error_code": run.error_code,
        }
        for run in runs
    ]
    comparison: dict[str, object] = {
        **dict(row.comparison or {}),
        "target_node_key": str((row.parameters or {}).get("target_node_key") or "video"),
        "formal_artifacts": formal,
        "candidate_artifacts": candidates,
        "run_states": run_states,
        "all_runs_terminal": bool(runs)
        and all(run.status in {*_DONE, "failed", "cancelled"} for run in runs),
    }
    return candidate_ids, comparison, runs


async def _latest_formal_artifact_ids(
    session: SessionDep,
    *,
    project_id: UUID,
    shot_id: UUID,
    node_key: str,
) -> list[str]:
    rows = list(
        (
            await session.execute(
                select(NodeRun, GraphNode)
                .join(GraphNode, GraphNode.id == NodeRun.graph_node_id)
                .where(
                    NodeRun.project_id == project_id,
                    GraphNode.node_key == node_key,
                    NodeRun.status.in_(_DONE),
                    NodeRun.result_artifact_id.is_not(None),
                )
            )
        )
        .tuples()
        .all()
    )
    matching = [
        run
        for run, _node in rows
        if str((run.input_snapshot or {}).get("shot_id") or "") == str(shot_id)
        and run_experiment_id(run.input_snapshot) is None
    ]
    latest = max(
        matching,
        key=lambda item: (item.attempt_no, item.created_at, str(item.id)),
        default=None,
    )
    return [str(latest.result_artifact_id)] if latest and latest.result_artifact_id else []


async def _resolve_model_binding(
    session: SessionDep,
    *,
    project: Project,
    selected_model: str,
    target_node_key: str,
) -> ProviderModelBinding:
    provider_type, separator, model_id = selected_model.partition("/")
    if not separator or not provider_type or not model_id:
        raise ValidationAppError(
            "experiment model id must be provider/model",
            details={"code": "MODEL_ID_INVALID"},
        )
    purpose = _TARGET_PURPOSE[target_node_key]
    binding = await session.scalar(
        select(ProviderModelBinding)
        .join(ProviderConnection, ProviderConnection.id == ProviderModelBinding.connection_id)
        .outerjoin(
            ModelCatalogEntry,
            ModelCatalogEntry.id == ProviderModelBinding.catalog_entry_id,
        )
        .where(
            ProviderModelBinding.workspace_id == project.workspace_id,
            ProviderModelBinding.enabled.is_(True),
            ProviderModelBinding.purpose == purpose,
            ProviderConnection.provider_type == provider_type,
            ProviderConnection.enabled.is_(True),
            or_(
                ModelCatalogEntry.model_id == model_id,
                ProviderModelBinding.model_id == model_id,
                ProviderModelBinding.invoke_model_value == model_id,
            ),
        )
        .order_by(
            ProviderModelBinding.quality_gated.desc(),
            ProviderModelBinding.account_verified.desc(),
            ProviderModelBinding.updated_at.desc(),
        )
    )
    if binding is None:
        raise ValidationAppError(
            "selected experiment model has no enabled workspace binding",
            details={
                "code": "MODEL_BINDING_MISSING",
                "selected_model": selected_model,
                "purpose": purpose,
            },
        )
    return binding


async def _enqueue(session: SessionDep, run_ids: list[UUID]) -> list[str]:
    scheduler = NodeRunScheduler(session)
    jobs: list[str] = []
    failures: list[str] = []
    for run_id in run_ids:
        try:
            job_id = await scheduler.enqueue_node_run_only(run_id)
            jobs.append(job_id)
            if job_id.startswith("local:"):
                failures.append(f"{run_id}:local_forbidden")
        except Exception as exc:  # noqa: BLE001 - preserve committed runs for recovery
            failures.append(f"{run_id}:{type(exc).__name__}")
    if failures:
        raise ValidationAppError(
            "QUEUE_UNAVAILABLE: experiment NodeRuns were committed but could not all be enqueued",
            details={"code": "QUEUE_UNAVAILABLE", "failures": failures},
        )
    return jobs


async def _experiment_or_404(
    session: SessionDep,
    *,
    project_id: UUID,
    experiment_id: UUID,
    for_update: bool = False,
) -> ExperimentBranch:
    statement = select(ExperimentBranch).where(
        ExperimentBranch.id == experiment_id,
        ExperimentBranch.project_id == project_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("experiment branch not found")
    return row


async def _promote_candidate(
    session: SessionDep,
    *,
    row: ExperimentBranch,
    candidate_run: NodeRun,
    user_id: UUID,
    adoption_scope: str,
) -> NodeRun:
    if candidate_run.result_artifact_id is None:
        raise ConflictError("experiment candidate has no Artifact")
    node = await session.get(GraphNode, candidate_run.graph_node_id)
    if node is None:
        raise ConflictError("experiment candidate node is missing")
    shot_id = row.source_shot_id
    if shot_id is None:
        raise ConflictError("experiment has no source shot")
    idempotency_key = (
        f"experiment-adopt:{row.id}:{shot_id}:{node.node_key}:"
        f"{candidate_run.result_artifact_id}:{adoption_scope}"
    )
    existing = await session.scalar(
        select(NodeRun).where(
            NodeRun.project_id == row.project_id,
            NodeRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    attempt = int(
        await session.scalar(
            select(func.coalesce(func.max(NodeRun.attempt_no), 0)).where(
                NodeRun.project_id == row.project_id,
                NodeRun.graph_version_id == candidate_run.graph_version_id,
                NodeRun.graph_node_id == candidate_run.graph_node_id,
            )
        )
        or 0
    ) + 1
    snapshot = {
        **dict(candidate_run.input_snapshot or {}),
        "execution_branch": "formal",
        "adopted_from_experiment_id": str(row.id),
        "adopted_candidate_run_id": str(candidate_run.id),
        "adoption_scope": adoption_scope,
    }
    snapshot.pop("experiment_id", None)
    fingerprint = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    promoted = NodeRun(
        project_id=row.project_id,
        graph_version_id=candidate_run.graph_version_id,
        graph_node_id=candidate_run.graph_node_id,
        attempt_no=attempt,
        idempotency_key=idempotency_key,
        input_hash=fingerprint,
        status="completed",
        input_snapshot=snapshot,
        output_summary={
            **dict(candidate_run.output_summary or {}),
            "formal_adoption": True,
            "adopted_from_experiment_id": str(row.id),
            "adopted_candidate_run_id": str(candidate_run.id),
        },
        result_artifact_id=candidate_run.result_artifact_id,
        reused_from_run_id=candidate_run.id,
        created_by=user_id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(promoted)
    await session.flush()
    return promoted


@router.get("/projects/{project_id}/experiments", response_model=list[ExperimentRead])
async def list_experiments(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> list[ExperimentRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    rows = (
        (
            await session.execute(
                select(ExperimentBranch)
                .where(ExperimentBranch.project_id == project_id)
                .order_by(ExperimentBranch.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    result: list[ExperimentRead] = []
    for row in rows:
        candidate_ids, comparison, _runs = await _candidate_state(session, row)
        result.append(
            _read(row, candidate_artifact_ids=candidate_ids, comparison=comparison)
        )
    return result


@router.post("/projects/{project_id}/experiments", response_model=ExperimentRead, status_code=201)
async def create_experiment(
    project_id: UUID,
    body: ExperimentCreateBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ExperimentRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    existing = (
        await session.execute(
            select(ExperimentBranch).where(
                ExperimentBranch.project_id == project_id,
                ExperimentBranch.idempotency_key == body.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        candidate_ids, comparison, _runs = await _candidate_state(session, existing)
        return _read(existing, candidate_artifact_ids=candidate_ids, comparison=comparison)
    if body.source_shot_id is not None:
        shot = await session.get(Shot, body.source_shot_id)
        if shot is None or shot.project_id != project_id:
            raise NotFoundError("source shot not found")
    target_node_key = str(body.parameters.get("target_node_key") or "video")
    if target_node_key not in _TARGET_PURPOSE:
        raise ValidationAppError("experiment target must be keyframe or video")
    source_artifact_ids = list(body.source_artifact_ids)
    if not source_artifact_ids and body.source_shot_id is not None:
        source_artifact_ids = await _latest_formal_artifact_ids(
            session,
            project_id=project_id,
            shot_id=body.source_shot_id,
            node_key=target_node_key,
        )
    row = ExperimentBranch(
        project_id=project_id,
        source_shot_id=body.source_shot_id,
        created_by=user.id,
        idempotency_key=body.idempotency_key,
        name=body.name,
        branch_type=body.branch_type,
        source_artifact_ids=source_artifact_ids,
        parameters={**dict(body.parameters), "target_node_key": target_node_key},
        selected_model=body.selected_model,
    )
    session.add(row)
    await session.commit()
    return _read(row)


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/start",
    response_model=ExperimentStartRead,
)
async def start_experiment(
    project_id: UUID,
    experiment_id: UUID,
    body: ExperimentStartBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ExperimentStartRead:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    row = await _experiment_or_404(
        session,
        project_id=project_id,
        experiment_id=experiment_id,
        for_update=True,
    )
    if row.status not in {"draft", "active"}:
        raise ConflictError("experiment branch already decided")
    existing_run_ids = _parameter_run_ids(row)
    if row.status == "active" and existing_run_ids:
        candidate_ids, comparison, _runs = await _candidate_state(session, row)
        return ExperimentStartRead(
            experiment=_read(
                row,
                candidate_artifact_ids=candidate_ids,
                comparison=comparison,
            ),
            run_ids=existing_run_ids,
            job_ids=[],
        )
    if row.source_shot_id is None:
        raise ConflictError("experiment requires a source shot")
    if not row.selected_model:
        raise ConflictError("experiment requires a selected model")
    binding = await _resolve_model_binding(
        session,
        project=project,
        selected_model=row.selected_model,
        target_node_key=body.target_node_key,
    )
    if not row.source_artifact_ids:
        row.source_artifact_ids = await _latest_formal_artifact_ids(
            session,
            project_id=project_id,
            shot_id=row.source_shot_id,
            node_key=body.target_node_key,
        )
    run_ids = await start_shot_nodes(
        session,
        project_id=project_id,
        shot_id=row.source_shot_id,
        user_id=user.id,
        node_keys=[body.target_node_key],
        force=True,
        include_missing_dependencies=True,
        experiment_id=row.id,
        model_binding_id=binding.id,
        model_binding_node_key=body.target_node_key,
    )
    row.status = "active"
    row.parameters = {
        **dict(row.parameters or {}),
        "target_node_key": body.target_node_key,
        "run_ids": [str(value) for value in run_ids],
        "model_binding_id": str(binding.id),
    }
    await session.commit()
    job_ids = await _enqueue(session, run_ids)
    candidate_ids, comparison, _runs = await _candidate_state(session, row)
    return ExperimentStartRead(
        experiment=_read(
            row,
            candidate_artifact_ids=candidate_ids,
            comparison=comparison,
        ),
        run_ids=run_ids,
        job_ids=job_ids,
    )


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/decision",
    response_model=ExperimentRead,
)
async def decide_experiment(
    project_id: UUID,
    experiment_id: UUID,
    body: ExperimentDecisionBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ExperimentRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    row = await _experiment_or_404(
        session,
        project_id=project_id,
        experiment_id=experiment_id,
        for_update=True,
    )
    if row.status not in {"draft", "active"}:
        raise ConflictError("experiment branch already decided")
    candidate_ids, comparison, runs = await _candidate_state(session, row)
    row.candidate_artifact_ids = candidate_ids
    row.comparison = comparison

    if body.decision == "kept":
        row.status = "active"
        row.comparison = {**comparison, "decision": "kept_as_experiment"}
        await session.commit()
        return _read(row, candidate_artifact_ids=candidate_ids, comparison=row.comparison)

    if body.decision == "rejected":
        row.status = "rejected"
        row.decided_at = datetime.now(UTC)
        row.comparison = {**comparison, "decision": "rejected"}
        await session.commit()
        return _read(row, candidate_artifact_ids=candidate_ids, comparison=row.comparison)

    # Keep the pre-v2 decision contract compatible for draft records created by
    # older clients. A bare ``accepted`` decision records acceptance only when
    # no candidate has been generated yet; once candidates exist, the user must
    # choose an explicit adoption scope so formal lineage cannot be ambiguous.
    if body.adoption_scope is None and not candidate_ids and not runs:
        row.status = "accepted"
        row.decided_at = datetime.now(UTC)
        row.comparison = {**comparison, "decision": "accepted_without_candidate"}
        await session.commit()
        return _read(row, candidate_artifact_ids=candidate_ids, comparison=row.comparison)
    if body.adoption_scope is None:
        raise ConflictError("accepting an experiment requires an adoption scope")
    target_node_key = str((row.parameters or {}).get("target_node_key") or "video")
    if body.adoption_scope.startswith("keyframe_") and target_node_key != "keyframe":
        raise ConflictError("keyframe adoption scope requires a keyframe experiment")
    requested_artifact_id = body.candidate_artifact_id
    if requested_artifact_id is None and candidate_ids:
        requested_artifact_id = UUID(candidate_ids[-1])
    candidate_run = next(
        (
            run
            for run in reversed(runs)
            if run.result_artifact_id == requested_artifact_id
            and str((run.input_snapshot or {}).get("node_key") or "") == target_node_key
        ),
        None,
    )
    if candidate_run is None:
        raise ConflictError("selected experiment candidate is not ready")
    promoted = await _promote_candidate(
        session,
        row=row,
        candidate_run=candidate_run,
        user_id=user.id,
        adoption_scope=body.adoption_scope,
    )
    downstream_run_ids: list[UUID] = []
    stale_nodes: list[str] = []
    if body.adoption_scope == "keyframe_keep_video":
        stale_nodes = list(_DOWNSTREAM_AFTER_KEYFRAME)
    elif body.adoption_scope == "keyframe_rerun_downstream":
        assert row.source_shot_id is not None
        downstream_run_ids = await start_shot_nodes(
            session,
            project_id=project_id,
            shot_id=row.source_shot_id,
            user_id=user.id,
            node_keys=list(_DOWNSTREAM_AFTER_KEYFRAME),
            force=True,
            include_missing_dependencies=True,
        )
    elif body.adoption_scope == "current_node":
        stale_nodes = {
            "keyframe": list(_DOWNSTREAM_AFTER_KEYFRAME),
            "video": ["video_drift_review", "composite", "continuity_review"],
        }.get(target_node_key, [])

    adopted_shot_ids = [str(value) for value in body.adopted_shot_ids]
    if row.source_shot_id is not None and str(row.source_shot_id) not in adopted_shot_ids:
        adopted_shot_ids.append(str(row.source_shot_id))
    row.adopted_shot_ids = list(dict.fromkeys(adopted_shot_ids))
    row.status = "accepted"
    row.decided_at = datetime.now(UTC)
    row.comparison = {
        **comparison,
        "decision": "accepted",
        "adoption_scope": body.adoption_scope,
        "promoted_run_id": str(promoted.id),
        "promoted_artifact_id": str(promoted.result_artifact_id),
        "stale_formal_node_keys": stale_nodes,
        "downstream_run_ids": [str(value) for value in downstream_run_ids],
    }
    await session.commit()
    if downstream_run_ids:
        await _enqueue(session, downstream_run_ids)
    return _read(row, candidate_artifact_ids=candidate_ids, comparison=row.comparison)


class ExperimentCreateRead(BaseModel):
    id: UUID
    name: str
    experiment_type: str
    status: str


@router.post("/projects/{project_id}/experiments", response_model=ExperimentCreateRead)
async def create_production_experiment(
    project_id: UUID,
    body: ExperimentCreateInput,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ExperimentCreateRead:
    """Create a Phase 5 experiment with per-shot snapshots (03 §47)."""
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    experiment = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=body,
    )
    await session.commit()
    return ExperimentCreateRead(
        id=experiment.id,
        name=experiment.name,
        experiment_type=experiment.experiment_type,
        status=experiment.status,
    )


class ExperimentAdoptBody(BaseModel):
    scope: Literal[
        "current_result_only",
        "keyframe_only",
        "keyframe_and_rerun_video",
        "design_only",
        "full_shot",
    ]


class ExperimentAdoptRead(BaseModel):
    id: UUID
    status: str
    adopted_scope: str


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/adopt",
    response_model=ExperimentAdoptRead,
)
async def adopt_experiment(
    project_id: UUID,
    experiment_id: UUID,
    body: ExperimentAdoptBody,
    user: CurrentUser,
    session: SessionDep,
    _csrf: CsrfDep,
) -> ExperimentAdoptRead:
    """Adopt selected experiment results onto the formal line (03 §50)."""
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    experiment = await ExperimentService(session).adopt_experiment(
        project=project,
        experiment_id=experiment_id,
        scope=body.scope,
    )
    await session.commit()
    return ExperimentAdoptRead(
        id=experiment.id,
        status=experiment.status,
        adopted_scope=body.scope,
    )
