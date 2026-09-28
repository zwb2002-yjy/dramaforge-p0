"""Read-only production snapshots and Artifact evidence delivery."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select

from app.access.projects import ProjectService
from app.api.deps import CurrentUser, SessionDep, require_selected_workspace
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.read_models import (
    ArtifactRead,
    NodeRunRead,
    ProductionArtifactPage,
    ProductionRunPage,
    ProductionRunStatusRead,
    ProductionSummaryRead,
    ProjectSnapshot,
    ProviderOperationRead,
    UpstreamDependencyRead,
)
from app.production.read_service import ProductionReadService
from app.shared.errors import NotFoundError, ValidationAppError

router = APIRouter(tags=["production"], dependencies=[Depends(require_selected_workspace)])


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

    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
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

    if role not in {"start", "mid", "end", "scene_change_1", "scene_change_2"}:
        raise ValidationAppError(
            "video frame role must be start, mid, end, scene_change_1, or scene_change_2",
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
    project = await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
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
    from app.execution.runtime_invariants import evaluate_required_dependencies_many

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
    decisions = await evaluate_required_dependencies_many(session, runs=runs)
    for run in runs:
        decision = decisions[run.id]
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
                connection_id=operation.connection_id,
                provider_connection_revision_id=operation.provider_connection_revision_id,
                credential_revision_id=operation.credential_revision_id,
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


@router.get("/projects/{project_id}/production-summary", response_model=ProductionSummaryRead)
async def production_summary(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> ProductionSummaryRead:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await ProductionReadService(session).summary(project_id=project_id)


@router.get("/projects/{project_id}/node-runs/status", response_model=list[ProductionRunStatusRead])
async def production_run_statuses(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    run_id: Annotated[list[UUID], Query(min_length=1, max_length=100)],
) -> list[ProductionRunStatusRead]:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await ProductionReadService(session).statuses(project_id=project_id, run_ids=run_id)


@router.get("/projects/{project_id}/production-history/runs", response_model=ProductionRunPage)
async def production_run_history(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> ProductionRunPage:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await ProductionReadService(session).runs(
        project_id=project_id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/projects/{project_id}/production-history/artifacts",
    response_model=ProductionArtifactPage,
)
async def production_artifact_history(
    project_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    usable_audio: bool = False,
) -> ProductionArtifactPage:
    await ProjectService(session).get_project_for_owner(project_id=project_id, actor=user)
    return await ProductionReadService(session).artifacts(
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        usable_audio=usable_audio,
    )
