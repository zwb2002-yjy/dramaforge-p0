"""Product execution path: enqueue NodeRun for Worker (no Adapter in request thread)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.consistency.face_review import face_review_images
from app.creation.models import CreationPlan
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.service import GraphService
from app.providers.fake import FakeFluxAdapter
from app.shared.errors import ValidationAppError
from app.storage.minio_store import ObjectStore, get_object_store


@dataclass(frozen=True)
class EnqueueKeyframeResult:
    graph_id: UUID
    graph_version_id: UUID
    node_run_id: UUID
    graph_node_id: UUID


@dataclass(frozen=True)
class ExecuteNodeResult:
    node_run_id: UUID
    artifact_id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    face_status: str | None
    face_score: float | None
    provider_operation_id: UUID
    node_type: str


# Back-compat alias
ExecuteKeyframeResult = ExecuteNodeResult


def _input_hash(payload: dict[str, object]) -> str:
    raw = repr(sorted(payload.items())).encode()
    return hashlib.sha256(raw).hexdigest()


async def enqueue_keyframe_after_plan(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    plan: CreationPlan,
    materialization_ops: list[str],
) -> EnqueueKeyframeResult:
    """Publish graph version and queue keyframe NodeRun — Worker executes Adapter."""
    graphs = GraphService(session)
    shot_id = uuid4()
    graph = await graphs.create_graph(
        project_id=project_id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key="shot-p0-v1",
        created_by=user_id,
        definition={
            "nodes": [{"key": "keyframe.generate", "type": "keyframe"}],
            "edges": [],
            "materialization": materialization_ops,
            "plan_id": str(plan.id),
        },
    )
    assert graph.current_version_id is not None
    version = await graphs.get_version(graph.current_version_id)
    node = GraphNode(
        graph_version_id=version.id,
        node_key="keyframe.generate",
        node_type="keyframe",
        display_name="Keyframe",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    snapshot: dict[str, object] = {
        "plan_id": str(plan.id),
        "plan": plan.plan,
        "materialization": materialization_ops,
    }
    ih = _input_hash(snapshot)
    node_run = NodeRun(
        project_id=project_id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=f"keyframe:{shot_id}:{ih}",
        input_hash=ih,
        status="queued",
        input_snapshot=snapshot,
        created_by=user_id,
    )
    session.add(node_run)
    await session.flush()
    return EnqueueKeyframeResult(
        graph_id=graph.id,
        graph_version_id=version.id,
        node_run_id=node_run.id,
        graph_node_id=node.id,
    )


async def execute_keyframe_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore | None = None,
    flux: FakeFluxAdapter | None = None,
    face_threshold: float = 0.35,
    require_canonical: bool = False,
    canonical_embedding: list[float] | None = None,
    canonical_image_bytes: bytes | None = None,
) -> ExecuteNodeResult:
    """Worker: Adapter → ObjectStore → Artifact → face review from *image bytes*."""
    return await execute_media_node_run(
        session,
        node_run_id=node_run_id,
        store=store,
        flux=flux,
        face_threshold=face_threshold,
        require_canonical=require_canonical,
        canonical_embedding=canonical_embedding,
        canonical_image_bytes=canonical_image_bytes,
    )


async def execute_media_node_run(
    session: AsyncSession,
    *,
    node_run_id: UUID,
    store: ObjectStore | None = None,
    flux: FakeFluxAdapter | None = None,
    face_threshold: float = 0.35,
    require_canonical: bool = False,
    canonical_embedding: list[float] | None = None,
    canonical_image_bytes: bytes | None = None,
) -> ExecuteNodeResult:
    """Worker entry for shot-p0-v1 media nodes. Never called from user Route."""
    from datetime import UTC, datetime

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        raise ValidationAppError("node_run not found")
    node = await session.get(GraphNode, run.graph_node_id)
    if node is None:
        raise ValidationAppError("graph_node not found")
    node_type = node.node_type

    if run.status in {"completed", "cached", "completed_after_cancel"}:
        art = await session.get(Artifact, run.result_artifact_id) if run.result_artifact_id else None
        if art is None:
            raise ValidationAppError("completed run missing artifact")
        return ExecuteNodeResult(
            node_run_id=run.id,
            artifact_id=art.id,
            object_key=art.object_key,
            content_hash=art.content_hash,
            byte_size=art.byte_size,
            face_status=str((run.output_summary or {}).get("face_review"))
            if run.output_summary
            else None,
            face_score=(
                float(run.output_summary["face_score"])
                if run.output_summary and run.output_summary.get("face_score") is not None
                else None
            ),
            provider_operation_id=uuid4(),
            node_type=node_type,
        )

    adapter = flux or FakeFluxAdapter()
    obj_store = store or get_object_store()
    snap = run.input_snapshot or {}
    # Resolve canonical from snapshot object key before enforce (Worker path).
    if canonical_image_bytes is None:
        snap_canon = snap.get("canonical_object_key")
        if isinstance(snap_canon, str) and snap_canon:
            try:
                canonical_image_bytes = await obj_store.get_bytes(object_key=snap_canon)
            except Exception:
                canonical_image_bytes = None
    if require_canonical and canonical_embedding is None and canonical_image_bytes is None:
        run.status = "failed"
        run.error_code = "CANONICAL_REFERENCE_REQUIRED"
        run.error_summary = "canonical reference required"
        await session.flush()
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")

    run.status = "running"
    run.started_at = datetime.now(UTC)
    await session.flush()

    prompt = str(snap.get("plan", {}))
    if isinstance(snap.get("plan"), dict):
        prompt = str(snap["plan"].get("prompt", prompt))
    else:
        prompt = str(snap.get("prompt", f"{node_type}:{run.id}"))

    # Produce media bytes by node type via Adapter contract
    kind = node_type
    create = await adapter.create({"prompt": prompt, "kind": kind})
    remote = str(create.get("remote_task_id") or uuid4())
    poll = await adapter.poll(remote)
    cost = await adapter.fetch_cost(remote)
    status = str(poll.get("status", "failed"))
    if status not in {"succeeded", "completed", "success"}:
        run.status = "failed"
        run.error_code = "PROVIDER_FAILED"
        run.error_summary = str(poll.get("error") or status)[:500]
        run.finished_at = datetime.now(UTC)
        await session.flush()
        raise ValidationAppError(f"PROVIDER_FAILED: {run.error_summary}")

    if hasattr(adapter, "blobs") and remote in getattr(adapter, "blobs", {}):
        data = adapter.blobs[remote]  # type: ignore[attr-defined]
    else:
        data = f"{kind}-STUB:{remote}:{prompt}".encode()

    # Node-specific mime / key
    mime, ext, art_type = _mime_for_node(node_type)
    object_key = f"projects/{run.project_id}/nodes/{node.node_key}/{run.id}.{ext}"
    stored = await obj_store.put_bytes(object_key=object_key, data=data, mime_type=mime)

    op = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind=f"{node_type}.generate",
        actual_provider=getattr(adapter, "provider", "flux"),
        actual_model=f"fake-{node_type}",
        provider_operation_id=remote,
        request_fingerprint=hashlib.sha256(f"{kind}:{prompt}".encode()).hexdigest(),
        status="succeeded",
        request_summary={"kind": kind},
        response_summary={"status": status},
        provider_cost=Decimal(str(cost.get("amount", 0.0))),
        currency=str(cost.get("currency", "USD")),
    )
    session.add(op)
    await session.flush()

    art = Artifact(
        project_id=run.project_id,
        artifact_type=art_type,
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
    )
    session.add(art)
    await session.flush()

    face_status: str | None = None
    face_score: float | None = None
    if node_type in {"keyframe", "face_review"}:
        # Two-source review only. Never self-match probe to itself.
        if canonical_image_bytes is not None:
            review = face_review_images(
                probe_image_bytes=data,
                canonical_image_bytes=canonical_image_bytes,
                threshold=face_threshold,
            )
            face_status = review.status
            face_score = review.score
        else:
            face_status = "needs_human"
            face_score = None

    run.status = "completed"
    run.result_artifact_id = art.id
    run.provider_cost = op.provider_cost or Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(art.id),
        "node_type": node_type,
        "face_review": face_status,
        "face_score": face_score,
        "byte_size": art.byte_size,
        "content_hash": art.content_hash,
    }
    node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteNodeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        face_status=face_status,
        face_score=face_score,
        provider_operation_id=op.id,
        node_type=node_type,
    )


def _mime_for_node(node_type: str) -> tuple[str, str, str]:
    if node_type in {"keyframe", "face_review", "prompt_compose", "prompt"}:
        return "image/png", "png", "image"
    if node_type in {"video", "video_review", "composite"}:
        return "video/mp4", "mp4", "video"
    if node_type in {"voice"}:
        return "audio/wav", "wav", "audio"
    if node_type in {"subtitle"}:
        return "application/x-subrip", "srt", "subtitle"
    if node_type in {"continuity_review"}:
        return "application/json", "json", "document"
    return "application/octet-stream", "bin", "document"
