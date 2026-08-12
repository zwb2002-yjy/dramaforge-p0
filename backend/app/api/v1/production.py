"""Production snapshot / Outbox-Arq enqueue / export routes (no Adapter in API)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep, require_selected_workspace
from app.delivery.download import (
    authorize_export_download,
    fetch_export_bytes,
    verify_download_token,
)
from app.delivery.export_service import build_project_export
from app.director.legacy_guard import require_legacy_execution_allowed
from app.director.models import DirectorWorkflowRun
from app.events.models import OutboxEvent
from app.execution.models import Artifact, GraphNode, NodeRun
from app.runtime.scheduler import AgentRunScheduler
from app.shared.errors import ForbiddenError

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


class ProjectSnapshot(BaseModel):
    project_id: UUID
    name: str
    node_runs: list[NodeRunRead]
    artifacts: list[ArtifactRead]


class DispatchResponse(BaseModel):
    enqueued: int
    job_ids: list[str]


class EnqueueResponse(BaseModel):
    node_run_id: UUID
    status: str
    job_id: str


class ExportResponse(BaseModel):
    export_id: UUID
    timeline_hash: str
    srt_hash: str
    package_hash: str
    mp4_object_key: str | None
    mp4_hash: str | None
    mp4_error: str | None
    source_artifact_ids: list[UUID]
    source_node_run_ids: list[UUID]
    export_item_count: int


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
        from app.shared.errors import NotFoundError

        raise NotFoundError("artifact not found")
    store = get_object_store()
    try:
        data = await store.get_bytes(object_key=art.object_key)
    except KeyError as exc:
        from app.shared.errors import NotFoundError

        raise NotFoundError("artifact bytes not in object store") from exc
    media = art.mime_type or "application/octet-stream"
    return Response(content=data, media_type=media)


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
            )
            for a in arts
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
    director = await session.scalar(
        select(DirectorWorkflowRun.id).where(
            DirectorWorkflowRun.project_id == project_id
        )
    )
    if director is not None:
        unauthorized_run = await session.scalar(
            select(NodeRun.id).where(
                NodeRun.project_id == project_id,
                NodeRun.status == "queued",
                NodeRun.production_batch_id.is_(None),
            )
        )
        unauthorized_outbox = await session.scalar(
            select(OutboxEvent.id).where(
                OutboxEvent.project_id == project_id,
                OutboxEvent.status == "pending",
                OutboxEvent.topic == "node_run.enqueue",
            )
        )
        if unauthorized_run is not None or unauthorized_outbox is not None:
            await require_legacy_execution_allowed(
                session, project_id=project_id, action="legacy_project_dispatch"
            )
    sched = AgentRunScheduler(session)
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
    if run.production_batch_id is None:
        await require_legacy_execution_allowed(
            session, project_id=project_id, action="legacy_node_run_enqueue"
        )
    job_id = await AgentRunScheduler(session).enqueue_node_run_only(node_run_id)
    await session.refresh(run)
    return EnqueueResponse(node_run_id=run.id, status=run.status, job_id=job_id)


@router.post("/projects/{project_id}/exports", response_model=ExportResponse)
async def export_project(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> ExportResponse:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await require_legacy_execution_allowed(
        session, project_id=project_id, action="legacy_project_export"
    )
    result = await build_project_export(
        session,
        project_id=project_id,
        requested_by=user.id,
        shot_subtitles=[(str(i), f"Line {i}") for i in range(1, 11)],
        try_ffmpeg=True,
        require_approved=True,
    )
    return ExportResponse(
        export_id=result.export_id,
        timeline_hash=result.timeline_hash,
        srt_hash=result.srt_hash,
        package_hash=result.package_hash,
        mp4_object_key=result.mp4_object_key,
        mp4_hash=result.mp4_hash,
        mp4_error=result.mp4_error,
        source_artifact_ids=result.source_artifact_ids,
        source_node_run_ids=result.source_node_run_ids,
        export_item_count=result.export_item_count,
    )  # export_status available on service result if API extended later


class GoldenProduceResponse(BaseModel):
    shot_count: int
    character_id: UUID
    canonical_object_key: str
    export_id: UUID
    timeline_hash: str
    srt_hash: str
    package_hash: str
    face_checked: int
    continuity_checked: int
    content_hash: str


class DownloadGrantResponse(BaseModel):
    export_id: UUID
    object_key: str
    token: str
    expires_at: int


@router.post(
    "/projects/{project_id}/produce-golden",
    response_model=GoldenProduceResponse,
)
async def produce_golden_path(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
) -> GoldenProduceResponse:
    """Import frozen golden script if needed path via fixture, produce 10 shots, export."""
    from app.execution.golden_path import run_golden_p0_path

    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    await require_legacy_execution_allowed(
        session, project_id=project_id, action="legacy_produce_golden"
    )
    result = await run_golden_p0_path(
        session,
        project_id=project_id,
        user_id=user.id,
        try_ffmpeg=True,
    )
    await session.commit()
    return GoldenProduceResponse(
        shot_count=result.shot_count,
        character_id=result.character_id,
        canonical_object_key=result.canonical_object_key,
        export_id=result.export.export_id,
        timeline_hash=result.export.timeline_hash,
        srt_hash=result.export.srt_hash,
        package_hash=result.export.package_hash,
        face_checked=sum(1 for s in result.shots if s.face_checked),
        continuity_checked=sum(1 for s in result.shots if s.continuity_checked),
        content_hash=result.content_hash,
    )


@router.post(
    "/projects/{project_id}/exports/{export_id}/download-grant",
    response_model=DownloadGrantResponse,
)
async def grant_export_download(
    project_id: UUID,
    export_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    _: CsrfDep,
    object_role: str = "timeline_json",
) -> DownloadGrantResponse:
    await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    grant = await authorize_export_download(
        session, export_id=export_id, actor=user, object_role=object_role
    )
    if grant.project_id != project_id:
        raise ForbiddenError("export not in project")
    return DownloadGrantResponse(
        export_id=grant.export_id,
        object_key=grant.object_key,
        token=grant.token,
        expires_at=grant.expires_at,
    )


@router.get("/projects/{project_id}/exports/{export_id}/download")
async def download_export_object(
    project_id: UUID,
    export_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    token: str,
    object_role: str = "timeline_json",
) -> Response:
    """Authorized download: return raw file bytes (not JSON metadata)."""
    await ProjectService(session).get_project_for_owner(
        project_id=project_id, actor=user
    )
    grant = await authorize_export_download(
        session, export_id=export_id, actor=user, object_role=object_role
    )
    verify_download_token(
        token=token,
        export_id=export_id,
        project_id=project_id,
        object_key=grant.object_key,
        user_id=user.id,
    )
    data = await fetch_export_bytes(grant=grant)
    media = "application/octet-stream"
    name = grant.object_key.rsplit("/", 1)[-1]
    if object_role in {"timeline_json", "package_json"} or name.endswith(".json"):
        media = "application/json"
    elif object_role == "srt" or name.endswith(".srt"):
        media = "application/x-subrip"
    elif object_role in {"package", "package_zip"} or name.endswith(".zip"):
        media = "application/zip"
    elif object_role == "mp4" or name.endswith(".mp4"):
        media = "video/mp4"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-SHA256": __import__("hashlib").sha256(data).hexdigest(),
            "X-Export-Id": str(export_id),
            "X-Object-Key": grant.object_key,
        },
    )
