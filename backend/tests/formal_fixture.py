"""Synthetic review facts for tests; production Formal writers stay gated."""

from uuid import UUID, uuid4

from app.assets.models import Shot
from app.execution.models import Artifact, GraphNode, NodeRun
from app.production.review_gate import (
    REVIEW_NODE_KEYS,
    ReviewDecision,
    ReviewKind,
    record_human_decision,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def approve_candidate(
    session: AsyncSession,
    *,
    shot: Shot,
    artifact: Artifact,
    actor_id: UUID,
    video: bool = False,
    verdict: ReviewDecision = "approved",
):
    """Seed exact evidence and an explicit approved decision; never write Formal."""
    source = await session.get(NodeRun, artifact.produced_by_run_id)
    assert source is not None
    kind: ReviewKind = "video_drift" if video else "identity"
    key = REVIEW_NODE_KEYS[kind]
    node = await session.scalar(
        select(GraphNode).where(
            GraphNode.graph_version_id == source.graph_version_id,
            GraphNode.node_key == key,
        )
    )
    if node is None:
        # Old synthetic migration/golden fixtures predate review nodes. This
        # function is test-only and does not recover or reinterpret a real run.
        node = GraphNode(
            graph_version_id=source.graph_version_id,
            node_key=key,
            node_type="video_review" if video else "identity_review",
            display_name=key,
        )
        session.add(node)
        await session.flush()
    attempt = await session.scalar(
        select(func.max(NodeRun.attempt_no)).where(
            NodeRun.graph_node_id == node.id,
        )
    )
    review = NodeRun(
        project_id=shot.project_id,
        graph_version_id=source.graph_version_id,
        graph_node_id=node.id,
        attempt_no=int(attempt or 0) + 1,
        idempotency_key=f"fixture-review:{uuid4().hex}",
        input_hash=uuid4().hex * 2,
        input_snapshot={"shot_id": str(shot.id), "upstream_artifact_id": str(artifact.id)},
        status="queued",
        output_summary={"status": "needs_human"},
        created_by=actor_id,
    )
    session.add(review)
    await session.flush()
    evidence = Artifact(
        project_id=shot.project_id,
        artifact_type="document",
        storage_state="available",
        object_key=f"test-fixture/review/{uuid4().hex}.json",
        content_hash=uuid4().hex * 2,
        mime_type="application/json",
        byte_size=1,
        produced_by_run_id=review.id,
    )
    session.add(evidence)
    await session.flush()
    review.result_artifact_id, review.status = evidence.id, "completed"
    await session.flush()
    return await record_human_decision(
        session,
        project_id=shot.project_id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        review_node_run_id=review.id,
        review_kind=kind,
        decision=verdict,
        reason="Synthetic test fixture: this exact candidate was reviewed",
        actor_id=actor_id,
        shot_version=shot.version,
        request_key=uuid4().hex,
    )
