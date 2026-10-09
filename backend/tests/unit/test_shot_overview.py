"""Storyboard statuses are batch projections of execution and exact review facts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.assets.models import Shot
from app.delivery.models import HumanReviewDecision
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.review_gate import subject_fingerprint
from app.production.shot_overview import load_shot_overview
from app.workbench.scene_service import SceneWorkspaceService
from app.workbench.scene_summary import SceneSummaryService
from sqlalchemy import event
from test_scene_workspace_snapshot import _add_node_run, _make_env, _seed


async def test_newest_media_attempt_wins_and_unknown_is_separate_from_failure():
    engine, session = await _make_env()
    try:
        user, project, _episode, scene, shot = await _seed(session)
        shot.status = "failed"  # Raw historical state must not drive the modern projection.
        old = await _add_node_run(
            session, project_id=project.id, shot_id=shot.id, user=user, status="failed"
        )
        old.created_at = datetime.now(UTC) - timedelta(seconds=2)
        latest = await _add_node_run(
            session,
            project_id=project.id,
            shot_id=shot.id,
            user=user,
            status="running",
            attempt_no=2,
        )
        latest.created_at = datetime.now(UTC)
        await session.flush()
        facts = await load_shot_overview(session, project_id=project.id, shots=[shot])
        assert facts[shot.id] == {
            "pending_review": False,
            "generating": True,
            "generation_failed": False,
            "outcome_unknown": False,
        }
        operation = ProviderOperation(
            node_run_id=latest.id,
            attempt_no=1,
            purpose="primary",
            operation_kind="image.generate",
            actual_provider="mock",
            actual_model="mock",
            request_fingerprint="a" * 64,
            status="unknown_submission",
        )
        session.add(operation)
        latest.status = "failed"
        await session.flush()
        summary = (
            await SceneSummaryService(session).list_summaries(project_id=project.id, actor=user)
        )[0]
        assert summary["generating_count"] == 0 and summary["failed_count"] == 0
        assert summary["unknown_count"] == 1 and summary["risk_count"] == 1
        workspace = await SceneWorkspaceService(session).get_workspace(
            project_id=project.id, scene_id=scene.id, actor=user
        )
        assert workspace["overview"][str(shot.id)] == {
            "pending_review": False,
            "generating": False,
            "generation_failed": False,
            "outcome_unknown": True,
        }
        operation.status = "failed"
        await session.flush()
        assert (await load_shot_overview(session, project_id=project.id, shots=[shot]))[shot.id][
            "generation_failed"
        ] is True
    finally:
        await session.close()
        await engine.dispose()


async def test_review_supersession_fingerprint_and_formal_are_independent():
    engine, session = await _make_env()
    try:
        user, project, _episode, scene, shot = await _seed(session)
        run = await _add_node_run(
            session, project_id=project.id, shot_id=shot.id, user=user, status="completed"
        )
        subject = await session.get(Artifact, run.result_artifact_id)
        assert subject is not None
        assert (await load_shot_overview(session, project_id=project.id, shots=[shot]))[shot.id][
            "pending_review"
        ] is True
        proof = Artifact(
            project_id=project.id,
            artifact_type="review",
            mime_type="application/json",
            storage_state="available",
            object_key="proof",
            content_hash="b" * 64,
            byte_size=10,
        )
        session.add(proof)
        await session.flush()
        review_node = GraphNode(
            graph_version_id=run.graph_version_id,
            node_key="identity_review",
            node_type="identity_review",
            display_name="Identity review",
            cacheable=False,
        )
        session.add(review_node)
        await session.flush()
        review_run = NodeRun(
            project_id=project.id,
            graph_version_id=run.graph_version_id,
            graph_node_id=review_node.id,
            attempt_no=1,
            idempotency_key=uuid4().hex,
            input_hash="f" * 64,
            input_snapshot={
                "shot_id": str(shot.id),
                "node_key": "identity_review",
                "upstream_artifact_id": str(subject.id),
            },
            status="completed",
            result_artifact_id=proof.id,
            output_summary={"status": "needs_human"},
            created_by=user.id,
        )
        session.add(review_run)
        await session.flush()
        proof.produced_by_run_id = review_run.id
        await session.flush()
        fingerprint = subject_fingerprint(
            artifact_id=subject.id,
            artifact_content_hash=subject.content_hash,
            review_kind="identity",
            review_node_run_id=review_run.id,
            review_artifact_id=proof.id,
            review_evidence_hash=proof.content_hash,
        )
        decision = HumanReviewDecision(
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=subject.id,
            review_node_run_id=review_run.id,
            review_artifact_id=proof.id,
            review_kind="identity",
            subject_fingerprint=fingerprint,
            shot_version_at_decision=1,
            decision="approved",
            reason="Approved",
            actor_id=user.id,
            request_key=uuid4().hex,
            request_hash="c" * 64,
        )
        session.add(decision)
        await session.flush()
        assert (await load_shot_overview(session, project_id=project.id, shots=[shot]))[shot.id][
            "pending_review"
        ] is False
        assert shot.formal_keyframe_artifact_id is None
        proof.content_hash = "d" * 64
        await session.flush()
        assert (await load_shot_overview(session, project_id=project.id, shots=[shot]))[shot.id][
            "pending_review"
        ] is True
        newer = HumanReviewDecision(
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=subject.id,
            review_node_run_id=review_run.id,
            review_artifact_id=proof.id,
            review_kind="identity",
            subject_fingerprint=fingerprint,
            shot_version_at_decision=1,
            decision="rejected",
            reason="Rejected",
            actor_id=user.id,
            request_key=uuid4().hex,
            request_hash="e" * 64,
            supersedes_id=decision.id,
            created_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add(newer)
        await session.flush()
        # Supersession wins even when storage timestamps would place the new judgement first.
        assert (await load_shot_overview(session, project_id=project.id, shots=[shot]))[shot.id][
            "pending_review"
        ] is False
        newer.decision = "demo_confirmed"
        await session.flush()
        assert (await load_shot_overview(session, project_id=project.id, shots=[shot]))[shot.id][
            "pending_review"
        ] is True
        shot.formal_keyframe_artifact_id = subject.id
        await session.flush()
        assert (await load_shot_overview(session, project_id=project.id, shots=[shot]))[shot.id][
            "pending_review"
        ] is False
    finally:
        await session.close()
        await engine.dispose()


async def test_hundred_shot_summary_query_count_is_bounded_and_does_not_write():
    engine, session = await _make_env()
    try:
        user, project, _episode, scene, first = await _seed(session)
        shots = [first]
        for number in range(2, 101):
            shot = Shot(
                project_id=project.id,
                scene_id=scene.id,
                shot_number=number,
                sort_order=number,
                status="failed",
                visual_description="Fixture",
            )
            session.add(shot)
            shots.append(shot)
        await session.flush()
        for index, shot in enumerate(shots):
            await _add_node_run(
                session,
                project_id=project.id,
                shot_id=shot.id,
                user=user,
                status=("queued", "failed", "completed")[index % 3],
            )
        await session.flush()
        statements: list[str] = []

        def record(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        summary = (
            await SceneSummaryService(session).list_summaries(project_id=project.id, actor=user)
        )[0]
        event.remove(engine.sync_engine, "before_cursor_execute", record)
        assert summary["shot_count"] == 100
        assert summary["generating_count"] == 34
        assert summary["failed_count"] == 33
        assert summary["pending_review_count"] == 33
        assert 0 < len(statements) <= 12
        assert set(statements) == {"SELECT"}
        assert all(shot.version == 1 and shot.formal_keyframe_artifact_id is None for shot in shots)
    finally:
        await session.close()
        await engine.dispose()
