"""Resolve immutable same-project Artifact inputs and freeze Review lineage."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.branches import branch_priority
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun
from app.shared.errors import (
    ValidationAppError,
)
from app.storage.minio_store import ObjectStore


def _artifact_snapshot(artifact: Artifact, *, prefix: str) -> dict[str, object]:
    return {
        f"{prefix}_artifact_id": str(artifact.id),
        f"{prefix}_object_key": artifact.object_key,
        f"{prefix}_content_hash": artifact.content_hash,
        f"{prefix}_mime_type": artifact.mime_type,
    }


async def _bind_review_input_artifacts(
    session: AsyncSession,
    *,
    run: NodeRun,
    node: GraphNode,
) -> dict[str, object]:
    """Freeze the direct same-Shot media input into a Review snapshot.

    A local repair may reuse a successful upstream from an earlier attempt.
    The exact source Run and attempt are frozen below so lineage remains
    reproducible without forcing unrelated nodes to share one attempt number.
    """
    upstream_key = {
        "identity_review": "keyframe",
        "video_drift_review": "video",
    }.get(node.node_key)
    if upstream_key is None:
        return dict(run.input_snapshot or {})
    upstream_node = await session.scalar(
        select(GraphNode)
        .join(GraphEdge, GraphEdge.upstream_node_id == GraphNode.id)
        .where(
            GraphEdge.graph_version_id == run.graph_version_id,
            GraphEdge.downstream_node_id == node.id,
            GraphEdge.required.is_(True),
            GraphNode.node_key == upstream_key,
        )
    )
    if upstream_node is None:
        raise ValidationAppError(
            f"{upstream_key} GraphEdge is missing",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    shot_id = str((run.input_snapshot or {}).get("shot_id") or "")
    candidates = list(
        (
            await session.execute(
                select(NodeRun).where(
                    NodeRun.project_id == run.project_id,
                    NodeRun.graph_version_id == run.graph_version_id,
                    NodeRun.graph_node_id == upstream_node.id,
                    NodeRun.status.in_({"completed", "cached"}),
                )
            )
        )
        .scalars()
        .all()
    )
    source = next(
        (
            candidate
            for candidate in sorted(
                candidates,
                key=lambda item: (
                    branch_priority(item.input_snapshot, run.input_snapshot) or 0,
                    item.attempt_no,
                    item.created_at,
                    str(item.id),
                ),
                reverse=True,
            )
            if str((candidate.input_snapshot or {}).get("shot_id") or "") == shot_id
            and branch_priority(candidate.input_snapshot, run.input_snapshot) is not None
        ),
        None,
    )
    if source is None:
        raise ValidationAppError(
            f"successful {upstream_key} Run is missing",
            details={"code": "UPSTREAM_RUN_MISSING"},
        )
    artifact = (
        await session.get(Artifact, source.result_artifact_id)
        if source.result_artifact_id
        else None
    )
    if artifact is None or artifact.project_id != run.project_id:
        raise ValidationAppError(
            f"successful {upstream_key} Artifact is missing",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        )
    snapshot = {
        **(run.input_snapshot or {}),
        "source_run_id": str(source.id),
        "source_attempt_no": source.attempt_no,
        # The durable link between this review and the media it judges. The
        # Formal-selection gate resolves a review by exactly this key, so binding
        # the source artifact without it leaves an approved candidate looking
        # unreviewed.
        "upstream_artifact_id": str(artifact.id),
        "upstream_node_run_id": str(source.id),
    }
    source_snapshot = source.input_snapshot or {}
    for field in (
        "canonical_artifact_id",
        "canonical_object_key",
        "canonical_content_hash",
        "canonical_mime_type",
    ):
        if field in source_snapshot:
            snapshot[field] = source_snapshot[field]
    prefix = "probe" if node.node_key == "identity_review" else "video"
    snapshot.update(_artifact_snapshot(artifact, prefix=prefix))
    run.input_snapshot = snapshot
    await session.flush()
    return snapshot


async def _read_bound_artifact(
    session: AsyncSession,
    *,
    run: NodeRun,
    snapshot: dict[str, object],
    prefix: str,
    store: ObjectStore,
    artifact_type: str,
) -> tuple[Artifact, bytes]:
    raw_id = snapshot.get(f"{prefix}_artifact_id")
    try:
        artifact_id = UUID(str(raw_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationAppError(
            f"{prefix} Artifact binding is missing",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        ) from exc
    artifact = await session.get(Artifact, artifact_id)
    expected = {
        "object_key": snapshot.get(f"{prefix}_object_key"),
        "content_hash": snapshot.get(f"{prefix}_content_hash"),
        "mime_type": snapshot.get(f"{prefix}_mime_type"),
    }
    if (
        artifact is None
        or artifact.project_id != run.project_id
        or artifact.artifact_type != artifact_type
        or artifact.storage_state != "available"
        or artifact.deleted_at is not None
        or artifact.object_key != expected["object_key"]
        or artifact.content_hash != expected["content_hash"]
        or artifact.mime_type != expected["mime_type"]
    ):
        raise ValidationAppError(
            f"{prefix} Artifact binding does not match available storage metadata",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        )
    try:
        data = await store.get_bytes(object_key=artifact.object_key)
    except Exception as exc:
        raise ValidationAppError(
            f"{prefix} Artifact bytes are unavailable",
            details={"code": "UPSTREAM_ARTIFACT_MISSING"},
        ) from exc
    if not data or hashlib.sha256(data).hexdigest() != artifact.content_hash:
        raise ValidationAppError(
            f"{prefix} Artifact hash mismatch",
            details={"code": "ARTIFACT_HASH_MISMATCH"},
        )
    return artifact, data
