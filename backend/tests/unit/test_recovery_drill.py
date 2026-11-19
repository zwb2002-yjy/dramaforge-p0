"""Recovery drills refuse to resume traffic on unrecoverable restored state (I10-01)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.execution.models import GraphNode, NodeRun, ProviderOperation
from app.maintenance.recovery_drill import MAX_RUNNING_LEASE, drill_recovery_state
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


async def _fixture(session: AsyncSession) -> tuple[Project, User, GraphNode]:
    suffix = uuid4().hex[:8]
    user = User(email=f"drill-{suffix}@example.com", display_name="D", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{suffix}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{suffix}",
        aspect_ratio="9:16",
        budget_limit=0,
        work_type="single_comic",
        planned_episode_count=1,
    )
    session.add(project)
    await session.flush()
    node = GraphNode(
        graph_version_id=uuid4(), node_key="video", node_type="video", display_name="Video"
    )
    session.add(node)
    await session.flush()
    return project, user, node


def _run(
    project,
    user,
    node,
    *,
    status: str,
    key: str,
    attempt_no: int = 1,
    started_at: datetime | None = None,
) -> NodeRun:
    # ``(graph_node_id, attempt_no)`` and ``(project_id, idempotency_key)`` are
    # unique, so each run gets its own attempt number and key.
    return NodeRun(
        project_id=project.id,
        graph_version_id=node.graph_version_id,
        graph_node_id=node.id,
        attempt_no=attempt_no,
        idempotency_key=key,
        input_hash="a" * 64,
        status=status,
        input_snapshot={},
        created_by=user.id,
        started_at=started_at,
    )


@pytest.mark.asyncio
async def test_a_clean_restored_state_passes_the_drills(session: AsyncSession) -> None:
    project, user, node = await _fixture(session)
    session.add(_run(project, user, node, status="queued", key="drill:1"))
    session.add(
        _run(
            project,
            user,
            node,
            status="running",
            key="drill:2",
            attempt_no=2,
            started_at=NOW - timedelta(minutes=5),
        )
    )
    await session.flush()
    report = await drill_recovery_state(session, now=NOW)
    assert report.passed is True
    assert report.as_dict()["checks"] == [
        "queue_idempotency",
        "running_lease",
        "unknown_submission_identity",
    ]


@pytest.mark.asyncio
async def test_blank_queue_key_blocks_re_enqueue(session: AsyncSession) -> None:
    project, user, node = await _fixture(session)
    session.add(_run(project, user, node, status="queued", key="   "))
    await session.flush()
    report = await drill_recovery_state(session, now=NOW)
    assert report.passed is False
    assert [failure["code"] for failure in report.failures] == ["DRILL_QUEUE_KEY_MISSING"]


@pytest.mark.asyncio
async def test_stale_and_orphaned_leases_are_reported(session: AsyncSession) -> None:
    project, user, node = await _fixture(session)
    session.add(
        _run(
            project,
            user,
            node,
            status="running",
            key="drill:stale",
            attempt_no=1,
            started_at=NOW - MAX_RUNNING_LEASE - timedelta(minutes=1),
        )
    )
    session.add(_run(project, user, node, status="running", key="drill:orphan", attempt_no=2))
    await session.flush()
    report = await drill_recovery_state(session, now=NOW)
    assert {failure["code"] for failure in report.failures} == {
        "DRILL_STALE_LEASE",
        "DRILL_ORPHANED_RUNNING",
    }

    # The same row is inside its lease a little earlier, so the check is time-based
    # rather than "running is always wrong".
    earlier = await drill_recovery_state(session, now=NOW - timedelta(minutes=59))
    assert "DRILL_STALE_LEASE" not in {failure["code"] for failure in earlier.failures}


@pytest.mark.asyncio
async def test_unknown_submission_claiming_a_remote_id_is_reported(
    session: AsyncSession,
) -> None:
    project, user, node = await _fixture(session)
    run = _run(project, user, node, status="running", key="drill:unknown", started_at=NOW)
    session.add(run)
    await session.flush()
    session.add(
        ProviderOperation(
            node_run_id=run.id,
            attempt_no=1,
            operation_kind="video",
            actual_provider="agnes",
            actual_model="agnes-video-2.5-flash",
            request_fingerprint="c" * 64,
            execution_path_version="unified-v1",
            status="unknown_submission",
            provider_operation_id="remote-that-cannot-be-polled",
        )
    )
    await session.flush()
    report = await drill_recovery_state(session, now=NOW)
    assert [failure["code"] for failure in report.failures] == ["DRILL_UNKNOWN_WITHOUT_REMOTE_ID"]
    assert report.failures[0]["node_run_id"] == str(run.id)
