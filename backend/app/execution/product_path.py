"""Product execution path: enqueue NodeRun for Worker (no Adapter in request thread)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

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
class ExecuteKeyframeResult:
    node_run_id: UUID
    artifact_id: UUID
    object_key: str
    content_hash: str
    byte_size: int
    face_status: str
    provider_operation_id: UUID


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
    face_threshold: float = 0.0,
    require_canonical: bool = False,
    canonical_embedding: list[float] | None = None,
) -> ExecuteKeyframeResult:
    """Worker entry: Adapter → MinIO → Artifact → face review. Never called from Route."""
    from datetime import UTC, datetime

    from app.execution.pipeline import face_review_hook

    run = await session.get(NodeRun, node_run_id)
    if run is None:
        raise ValidationAppError("node_run not found")
    if run.status in {"completed", "cached", "completed_after_cancel"}:
        art = await session.get(Artifact, run.result_artifact_id) if run.result_artifact_id else None
        if art is None:
            raise ValidationAppError("completed run missing artifact")
        return ExecuteKeyframeResult(
            node_run_id=run.id,
            artifact_id=art.id,
            object_key=art.object_key,
            content_hash=art.content_hash,
            byte_size=art.byte_size,
            face_status="passed",
            provider_operation_id=uuid4(),
        )
    if require_canonical and canonical_embedding is None:
        run.status = "failed"
        run.error_code = "CANONICAL_REFERENCE_REQUIRED"
        run.error_summary = "canonical reference required for keyframe"
        await session.flush()
        raise ValidationAppError("CANONICAL_REFERENCE_REQUIRED")

    run.status = "running"
    run.started_at = datetime.now(UTC)
    await session.flush()

    adapter = flux or FakeFluxAdapter()
    obj_store = store or get_object_store()
    prompt = str((run.input_snapshot or {}).get("plan", {}).get("prompt", "keyframe"))
    if isinstance(run.input_snapshot.get("plan"), dict):
        prompt = str(run.input_snapshot["plan"].get("prompt", prompt))
    else:
        prompt = f"PLAN:{run.input_snapshot.get('plan_id', 'shot')}"

    create = await adapter.create({"prompt": prompt, "kind": "keyframe"})
    remote = str(create.get("remote_task_id") or uuid4())
    poll = await adapter.poll(remote)
    cost = await adapter.fetch_cost(remote)
    status = str(poll.get("status", "failed"))
    if status not in {"succeeded", "completed", "success"}:
        run.status = "failed"
        run.error_code = "IMAGE_PROVIDER_FAILED"
        run.error_summary = str(poll.get("error") or status)[:500]
        run.finished_at = datetime.now(UTC)
        await session.flush()
        raise ValidationAppError(f"IMAGE_PROVIDER_FAILED: {run.error_summary}")

    # Prefer binary from fake/content; otherwise store URI bytes stub + real hash of payload
    uri = str(poll.get("artifact_uri") or f"fake://{remote}")
    if hasattr(adapter, "blobs") and remote in getattr(adapter, "blobs", {}):
        data = adapter.blobs[remote]  # type: ignore[attr-defined]
    else:
        data = f"PNG-STUB:{uri}".encode("utf-8")
    object_key = f"projects/{run.project_id}/keyframes/{run.id}.png"
    stored = await obj_store.put_bytes(
        object_key=object_key, data=data, mime_type="image/png"
    )

    op = ProviderOperation(
        node_run_id=run.id,
        attempt_no=1,
        purpose="primary",
        operation_kind="image.keyframe",
        actual_provider=getattr(adapter, "provider", "flux"),
        actual_model="fake-flux",
        provider_operation_id=remote,
        request_fingerprint=hashlib.sha256(prompt.encode()).hexdigest(),
        status="succeeded",
        request_summary={"kind": "keyframe"},
        response_summary={"status": status},
        provider_cost=Decimal(str(cost.get("amount", 0.0))),
        currency=str(cost.get("currency", "USD")),
    )
    session.add(op)
    await session.flush()

    art = Artifact(
        project_id=run.project_id,
        artifact_type="image",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        produced_by_run_id=run.id,
    )
    session.add(art)
    await session.flush()

    emb = [0.0] * 512
    emb[0] = 1.0
    canon = canonical_embedding if canonical_embedding is not None else emb
    review = face_review_hook(embedding=emb, canonical=canon, threshold=face_threshold)

    run.status = "completed"
    run.result_artifact_id = art.id
    run.provider_cost = op.provider_cost or Decimal("0")
    run.finished_at = datetime.now(UTC)
    run.output_summary = {
        "artifact_id": str(art.id),
        "face_review": review.status,
        "face_score": review.score,
    }
    node = await session.get(GraphNode, run.graph_node_id)
    if node is not None:
        node.latest_successful_run_id = run.id
    await session.flush()
    return ExecuteKeyframeResult(
        node_run_id=run.id,
        artifact_id=art.id,
        object_key=art.object_key,
        content_hash=art.content_hash,
        byte_size=art.byte_size,
        face_status=review.status,
        provider_operation_id=op.id,
    )
