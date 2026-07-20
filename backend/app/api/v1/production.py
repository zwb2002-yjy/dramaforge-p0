"""Production snapshot / Outbox-Arq enqueue / export routes (no Adapter in API)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CsrfDep, CurrentUser, SessionDep
from app.delivery.download import authorize_export_download, fetch_export_bytes, verify_download_token
from app.delivery.export_service import build_project_export
from app.execution.models import Artifact, NodeRun
from app.runtime.scheduler import AgentRunScheduler
from app.shared.errors import ForbiddenError

router = APIRouter(tags=["production"])


class NodeRunRead(BaseModel):
    id: UUID
    status: str
    input_hash: str
    result_artifact_id: UUID | None
    provider_cost: str
    output_summary: dict


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


@router.get("/projects/{project_id}/snapshot", response_model=ProjectSnapshot)
async def project_snapshot(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProjectSnapshot:
    project = await ProjectService(session).get_project_for_member(
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
            await session.execute(select(Artifact).where(Artifact.project_id == project_id))
        )
        .scalars()
        .all()
    )
    return ProjectSnapshot(
        project_id=project.id,
        name=project.name,
        node_runs=[
            NodeRunRead(
                id=r.id,
                status=r.status,
                input_hash=r.input_hash,
                result_artifact_id=r.result_artifact_id,
                provider_cost=str(r.provider_cost),
                output_summary=dict(r.output_summary or {}),
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
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    sched = AgentRunScheduler(session)
    n = await sched.dispatch_pending(worker_id=f"api-enqueue:{user.id}")
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
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    run = await session.get(NodeRun, node_run_id)
    if run is None or run.project_id != project_id:
        from app.shared.errors import NotFoundError

        raise NotFoundError("node_run not found")
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
    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
    result = await build_project_export(
        session,
        project_id=project_id,
        requested_by=user.id,
        shot_subtitles=[(str(i), f"Line {i}") for i in range(1, 11)],
        try_ffmpeg=True,
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

    await ProjectService(session).get_project_for_member(project_id=project_id, actor=user)
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
    await ProjectService(session).get_project_for_member(
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
) -> dict[str, object]:
    """Authorized download: membership + HMAC token (no permanent public URL)."""
    await ProjectService(session).get_project_for_member(
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
    return {
        "export_id": str(export_id),
        "object_key": grant.object_key,
        "byte_size": len(data),
        "content_sha256": __import__("hashlib").sha256(data).hexdigest(),
        "authorized": True,
    }
