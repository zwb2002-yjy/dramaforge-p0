"""Isolated media/review output fixtures; user gates remain real services."""

from uuid import uuid4

from sqlalchemy import select


async def approve_and_adopt(session, *, project, shot, user, run, video=False):
    """Isolated worker output fixture; approval/Formal use real domain gates."""
    from app.execution.models import Artifact, GraphNode, NodeRun
    from app.production.formal_selection import set_formal_keyframe, set_formal_video
    from app.production.repair_service import record_repair_adoption
    from app.production.review_gate import record_human_decision

    candidate = Artifact(
        project_id=project.id, artifact_type="video" if video else "image",
        storage_state="available", object_key=f"candidate/{uuid4().hex}",
        content_hash=uuid4().hex * 2, mime_type="video/mp4" if video else "image/png",
        byte_size=1, produced_by_run_id=run.id,
    )
    session.add(candidate)
    await session.flush()
    run.result_artifact_id = candidate.id
    run.status = "completed"
    review = await session.scalar(
        select(NodeRun).join(GraphNode, GraphNode.id == NodeRun.graph_node_id).where(
            NodeRun.graph_version_id == run.graph_version_id,
            GraphNode.node_key == ("video_drift_review" if video else "identity_review"),
        )
    )
    assert review is not None
    evidence = Artifact(
        project_id=project.id, artifact_type="review", storage_state="available",
        object_key=f"review/{uuid4().hex}", content_hash=uuid4().hex * 2,
        mime_type="application/json", byte_size=1, produced_by_run_id=review.id,
    )
    session.add(evidence)
    await session.flush()
    review.status = "completed"
    review.result_artifact_id = evidence.id
    review.input_snapshot = {**review.input_snapshot, "upstream_artifact_id": str(candidate.id)}
    review.output_summary = {"status": "needs_human"}
    await session.flush()
    decision = await record_human_decision(
        session, project_id=project.id, shot_id=shot.id, artifact_id=candidate.id,
        review_node_run_id=review.id, review_kind="video_drift" if video else "identity",
        decision="approved", reason="Reviewed this exact repair candidate",
        actor_id=user.id, shot_version=shot.version, request_key=uuid4().hex,
    )
    formal = set_formal_video if video else set_formal_keyframe
    await formal(session, project_id=project.id, shot_id=shot.id,
                 artifact_id=candidate.id, expected_shot_version=shot.version,
                 require_review_approval=True)
    assert await record_repair_adoption(
        session, project_id=project.id, shot_id=shot.id, artifact_id=candidate.id,
    ) == 1
    await session.commit()
    return candidate, decision
