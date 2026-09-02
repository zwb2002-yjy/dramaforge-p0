"""Production snapshot and Outbox-Arq enqueue routes (no Adapter in API)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.runtime.scheduler import NodeRunScheduler
from app.shared.errors import NotFoundError, ValidationAppError

router = APIRouter(
    tags=["production"], dependencies=[Depends(require_selected_workspace)]
)


class NodeRunRead(BaseModel):
    id: UUID
    attempt_no: int
    status: str
    node_key: str
    input_hash: str
    result_artifact_id: UUID | None
    provider_cost: str
    output_summary: dict[str, object]
    input_snapshot: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_summary: str | None = None
    upstream_dependencies: list[UpstreamDependencyRead] = Field(default_factory=list)


class UpstreamDependencyRead(BaseModel):
    node_key: str
    run_id: UUID | None
    status: str
    result_artifact_id: UUID | None


class ArtifactRead(BaseModel):
    id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    mime_type: str
    storage_state: str
    produced_by_run_id: UUID | None
    width: int | None
    height: int | None
    duration_seconds: str | None


class ProviderOperationRead(BaseModel):
    id: UUID
    node_run_id: UUID | None
    operation_kind: str
    actual_provider: str
    actual_model: str
    provider_request_id: str | None
    protocol_profile: str | None
    status: str
    request_fingerprint: str
    request_summary: dict[str, object]
    response_summary: dict[str, object]
    model_binding_id: UUID | None
    catalog_entry_id: UUID | None
    capability_manifest_hash: str | None
    execution_path_version: str | None
    provider_cost: str | None
    currency: str
    submitted_at: str | None
    completed_at: str | None


class ProjectSnapshot(BaseModel):
    project_id: UUID
    name: str
    node_runs: list[NodeRunRead]
    artifacts: list[ArtifactRead]
    provider_operations: list[ProviderOperationRead]


class DispatchResponse(BaseModel):
    enqueued: int
    job_ids: list[str]


class EnqueueResponse(BaseModel):
    node_run_id: UUID
    status: str
    job_id: str


def _public_provider_request_summary(operation: ProviderOperation) -> dict[str, object]:
    summary = dict(operation.request_summary or {})
    return {
        key: summary[key]
        for key in (
            "kind",
            "execution_path",
            "compiled_request",
            "effective_request",
            "translation_report",
            "reference_artifact_ids",
            "reference_fingerprints",
            "frozen_model_binding_id",
            "capability_manifest_hash",
        )
        if key in summary
    }


def _public_provider_response_summary(operation: ProviderOperation) -> dict[str, object]:
    summary = dict(operation.response_summary or {})
    return {
        key: summary[key]
        for key in (
            "create_status",
            "final_status",
            "poll_count",
            "query_kind",
            "provider_reported_cost",
            "cost_status",
        )
        if key in summary
    }


@router.get(
    "/projects/{project_id}/artifacts/{artifact_id}/content",
)
async def get_artifact_content(
    project_id: UUID,
    artifact_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    """Stream artifact bytes for the owning user's workspace."""
    from app.storage.minio_store import get_object_store

    await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    art = await session.get(Artifact, artifact_id)
    if art is None or art.project_id != project_id:
        raise NotFoundError("artifact not found")
    store = get_object_store()
    try:
        data = await store.get_bytes(object_key=art.object_key)
    except KeyError as exc:
        raise NotFoundError("artifact bytes not in object store") from exc
    media = art.mime_type or "application/octet-stream"
    return Response(content=data, media_type=media)


@router.get("/projects/{project_id}/artifacts/{artifact_id}/video-frames/{role}")
async def get_artifact_video_frame(
    project_id: UUID,
    artifact_id: UUID,
    role: str,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    """Return a deterministic start, middle, or end frame for human review."""
    from app.consistency.video_drift import extract_video_samples
    from app.storage.minio_store import get_object_store

    if role not in {"start", "mid", "end"}:
        raise ValidationAppError(
            "video frame role must be start, mid, or end",
            details={"code": "VIDEO_FRAME_ROLE_INVALID"},
        )
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    artifact = await session.get(Artifact, artifact_id)
    if (
        artifact is None
        or artifact.project_id != project_id
        or not artifact.mime_type.startswith("video/")
    ):
        raise NotFoundError("video Artifact not found")
    try:
        video = await get_object_store().get_bytes(object_key=artifact.object_key)
        sample = next(item for item in extract_video_samples(video) if item.role == role)
    except (KeyError, StopIteration, ValueError) as exc:
        raise ValidationAppError(
            "video frame evidence could not be decoded",
            details={"code": "VIDEO_FRAME_EVIDENCE_UNAVAILABLE"},
        ) from exc
    return Response(
        content=sample.image_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/projects/{project_id}/snapshot", response_model=ProjectSnapshot)
async def project_snapshot(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectSnapshot:
    project = await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    runs = list(
        (
            await session.execute(
                select(NodeRun)
                .where(NodeRun.project_id == project_id)
                .order_by(NodeRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    arts = list(
        (
            await session.execute(
                select(Artifact)
                .where(Artifact.project_id == project_id)
                .order_by(Artifact.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    operations = (
        list(
            (
                await session.execute(
                    select(ProviderOperation)
                    .where(ProviderOperation.node_run_id.in_([run.id for run in runs]))
                    .order_by(ProviderOperation.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if runs
        else []
    )
    from app.execution.runtime_invariants import evaluate_required_dependencies

    nodes = {
        node.id: node
        for node in (
            await session.execute(
                select(GraphNode).where(
                    GraphNode.graph_version_id.in_({run.graph_version_id for run in runs})
                )
            )
        )
        .scalars()
        .all()
    }
    dependency_by_run: dict[UUID, list[UpstreamDependencyRead]] = {}
    for run in runs:
        decision = await evaluate_required_dependencies(session, run=run)
        dependency_by_run[run.id] = [
            UpstreamDependencyRead(
                node_key=dependency.node_key,
                run_id=dependency.run_id,
                status=dependency.status,
                result_artifact_id=dependency.result_artifact_id,
            )
            for dependency in decision.dependencies
        ]
    return ProjectSnapshot(
        project_id=project.id,
        name=project.name,
        node_runs=[
            NodeRunRead(
                id=r.id,
                attempt_no=r.attempt_no,
                status=r.status,
                node_key=nodes[r.graph_node_id].node_key,
                input_hash=r.input_hash,
                result_artifact_id=r.result_artifact_id,
                provider_cost=str(r.provider_cost),
                output_summary=dict(r.output_summary or {}),
                input_snapshot=dict(r.input_snapshot or {}),
                idempotency_key=str(r.idempotency_key or ""),
                started_at=r.started_at.isoformat() if r.started_at else None,
                finished_at=r.finished_at.isoformat() if r.finished_at else None,
                error_code=r.error_code,
                error_summary=(r.error_summary or "")[:500] or None,
                upstream_dependencies=dependency_by_run[r.id],
            )
            for r in runs
        ],
        artifacts=[
            ArtifactRead(
                id=a.id,
                object_key=a.object_key,
                content_hash=a.content_hash,
                byte_size=a.byte_size,
                mime_type=a.mime_type,
                storage_state=a.storage_state,
                produced_by_run_id=a.produced_by_run_id,
                width=a.width,
                height=a.height,
                duration_seconds=(
                    str(a.duration_seconds) if a.duration_seconds is not None else None
                ),
            )
            for a in arts
        ],
        provider_operations=[
            ProviderOperationRead(
                id=operation.id,
                node_run_id=operation.node_run_id,
                operation_kind=operation.operation_kind,
                actual_provider=operation.actual_provider,
                actual_model=operation.actual_model,
                provider_request_id=operation.provider_operation_id,
                protocol_profile=operation.protocol_profile,
                status=operation.status,
                request_fingerprint=operation.request_fingerprint,
                request_summary=_public_provider_request_summary(operation),
                response_summary=_public_provider_response_summary(operation),
                model_binding_id=operation.model_binding_id,
                catalog_entry_id=operation.catalog_entry_id,
                capability_manifest_hash=operation.capability_manifest_hash,
                execution_path_version=operation.execution_path_version,
                provider_cost=(
                    str(operation.provider_cost) if operation.provider_cost is not None else None
                ),
                currency=operation.currency,
                submitted_at=(
                    operation.submitted_at.isoformat() if operation.submitted_at else None
                ),
                completed_at=(
                    operation.completed_at.isoformat() if operation.completed_at else None
                ),
            )
            for operation in operations
        ],
    )


@router.post(
    "/projects/{project_id}/dispatch",
    response_model=DispatchResponse,
)
async def dispatch_project_work(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> DispatchResponse:
    """Publish Outbox + enqueue Arq jobs only — does not run Adapters."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    sched = NodeRunScheduler(session)
    n = await sched.dispatch_pending(
        worker_id=f"api-enqueue:{user.id}",
        project_id=project_id,
    )
    return DispatchResponse(enqueued=n, job_ids=list(sched.enqueued_job_ids))


@router.post(
    "/projects/{project_id}/node-runs/{node_run_id}/enqueue",
    response_model=EnqueueResponse,
)
async def enqueue_node_run(
    project_id: UUID,
    node_run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> EnqueueResponse:
    """Enqueue Worker job for a NodeRun. Adapter runs only in Worker."""
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    run = await session.get(NodeRun, node_run_id)
    if run is None or run.project_id != project_id:
        from app.shared.errors import NotFoundError

        raise NotFoundError("node_run not found")
    response_run_id = run.id
    response_status = run.status
    job_id = await NodeRunScheduler(session).enqueue_node_run_only(node_run_id)
    # enqueue_node_run_only commits before publishing to Arq. PostgreSQL RLS
    # settings are transaction-local, so refreshing here would query without
    # the request's project scope and can race a fast Worker to a terminal state.
    return EnqueueResponse(
        node_run_id=response_run_id,
        status=response_status,
        job_id=job_id,
    )
