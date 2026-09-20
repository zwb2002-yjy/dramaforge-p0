"""Scalable reads preserve logical attempts, exact scope and complete history."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.execution.models import Artifact, GraphEdge, GraphNode, NodeRun
from app.execution.runtime_invariants import evaluate_required_dependencies_many
from app.production.read_service import ProductionReadService
from app.shared.errors import NotFoundError, ValidationAppError
from sqlalchemy import event
from tests.unit.test_scene_workspace_snapshot import _add_node_run, _make_env, _seed


@pytest.fixture
async def env():
    engine, session = await _make_env()
    user, project, _, _, shot = await _seed(session)
    yield engine, session, user, project, shot
    await session.close()
    await engine.dispose()


async def add_run(env, status="queued", attempt=1, **snapshot):
    _, session, user, project, shot = env
    run = await _add_node_run(
        session,
        project_id=project.id,
        shot_id=shot.id,
        user=user,
        status=status,
        attempt_no=attempt,
    )
    run.input_snapshot = {**run.input_snapshot, **snapshot}
    await session.flush()
    return run


async def test_summary_counts_effective_attempts_without_large_evidence(env):
    _, session, _, project, _ = env
    await add_run(env, "failed", 1)
    await add_run(env, "completed", 2, frozen_prompt="private" * 10000)
    await add_run(env, "running", 3, execution_branch="experiment", experiment_id="exp-1")
    latest_failure = await add_run(
        env, "failed", 4, execution_branch="experiment", experiment_id="exp-2"
    )
    summary = await ProductionReadService(session).summary(project_id=project.id)
    assert (
        summary.total_runs,
        summary.completed_runs,
        summary.running_runs,
        summary.failed_runs,
    ) == (
        3,
        1,
        1,
        1,
    )
    assert [run.id for run in summary.recent_failures] == [latest_failure.id]
    assert summary.artifact_count == 1
    assert "frozen_prompt" not in summary.model_dump_json()
    assert "input_snapshot" not in summary.model_dump_json()


async def test_status_lookup_is_bounded_exact_ordered_and_fails_closed(env):
    _, session, _, project, _ = env
    first = await add_run(env)
    second = await add_run(env, "completed", 2)
    service = ProductionReadService(session)
    result = await service.statuses(project_id=project.id, run_ids=[second.id, first.id])
    assert [row.id for row in result] == [second.id, first.id]
    assert set(result[0].model_dump()) == {"id", "status", "result_artifact_id"}
    for project_id, ids, error in [
        (project.id, [first.id, uuid4()], NotFoundError),
        (uuid4(), [first.id], NotFoundError),
        (project.id, [], ValidationAppError),
        (project.id, [first.id] * 101, ValidationAppError),
    ]:
        with pytest.raises(error):
            await service.statuses(project_id=project_id, run_ids=ids)


async def test_keyset_history_keeps_same_timestamp_rows_and_excludes_newer_inserts(env):
    _, session, _, project, _ = env
    timestamp = datetime(2026, 9, 1, tzinfo=UTC)
    rows = [await add_run(env, "completed", index + 1) for index in range(7)]
    for row in rows:
        row.created_at = timestamp
    await session.flush()
    service = ProductionReadService(session)
    first = await service.runs(project_id=project.id, limit=3)
    await add_run(env, "queued", 8)
    second = await service.runs(project_id=project.id, limit=3, cursor=first.next_cursor)
    third = await service.runs(project_id=project.id, limit=3, cursor=second.next_cursor)
    ids = [row.id for page in [first, second, third] for row in page.items]
    assert ids == sorted([row.id for row in rows], reverse=True)
    assert third.next_cursor is None
    assert (await service.runs(project_id=uuid4())).items == []
    artifacts = []
    cursor = None
    for _ in range(10):
        page = await service.artifacts(project_id=project.id, limit=2, cursor=cursor)
        artifacts.extend(page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    else:
        pytest.fail("artifact pagination did not terminate")
    assert len(artifacts) == len({row.id for row in artifacts}) == 7
    for invalid in ["bad-cursor", "!", "x" * 257]:
        with pytest.raises(ValidationAppError):
            await service.runs(project_id=project.id, cursor=invalid)


@pytest.mark.parametrize("size", [1, 30, 100])
async def test_dependency_and_summary_query_count_does_not_grow_per_run(env, size):
    engine, session, user, project, shot = env
    upstream = await add_run(env, "completed")
    node = GraphNode(
        graph_version_id=upstream.graph_version_id,
        node_key="video",
        node_type="video",
        display_name="Video",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    session.add(
        GraphEdge(
            graph_version_id=upstream.graph_version_id,
            upstream_node_id=upstream.graph_node_id,
            downstream_node_id=node.id,
            output_port="result",
            input_port="image",
            position=0,
            required=True,
        )
    )
    runs = [
        NodeRun(
            project_id=project.id,
            graph_version_id=upstream.graph_version_id,
            graph_node_id=node.id,
            attempt_no=index + 1,
            idempotency_key=uuid4().hex,
            input_hash=uuid4().hex * 2,
            input_snapshot={"shot_id": str(shot.id)},
            status="queued",
            created_by=user.id,
        )
        for index in range(size)
    ]
    session.add_all(runs)
    await session.flush()
    statements = []

    def record(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        decisions = await evaluate_required_dependencies_many(session, runs=runs)
        assert len(statements) == 4
        assert len(decisions) == size
        assert all(decision.action == "ready" for decision in decisions.values())
        statements.clear()
        summary = await ProductionReadService(session).summary(project_id=project.id)
        assert len(statements) == 4  # Fixed extra query for one failure per canonical stage.
        assert summary.total_runs == 2
        assert summary.running_runs == 1
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.parametrize(
    "status,adopted,expected",
    [
        ("queued", False, "defer"),
        ("running", False, "defer"),
        ("cancel_requested", False, "defer"),
        ("failed", False, "fail"),
        ("cancelled", False, "fail"),
        ("completed", False, "ready"),
        ("cached", False, "ready"),
        ("completed_after_cancel", False, "fail"),
        ("completed_after_cancel", True, "ready"),
    ],
)
async def test_batched_dependencies_keep_fail_closed_worker_semantics(
    env, status, adopted, expected
):
    _, session, user, project, shot = env
    source = await add_run(env, "completed" if status == "cached" else status)
    if status == "cached":
        original = source
        source = await add_run(env, "completed", 2)
        source.status = "cached"
        source.reused_from_run_id = original.id
        source.result_artifact_id = original.result_artifact_id
    source.output_summary = {"adopted_after_cancel": adopted}
    node = GraphNode(
        graph_version_id=source.graph_version_id,
        node_key="video",
        node_type="video",
        display_name="Video",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    session.add(
        GraphEdge(
            graph_version_id=source.graph_version_id,
            upstream_node_id=source.graph_node_id,
            downstream_node_id=node.id,
            output_port="result",
            input_port="image",
            position=0,
            required=True,
        )
    )
    target = NodeRun(
        project_id=project.id,
        graph_version_id=source.graph_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=uuid4().hex,
        input_hash=uuid4().hex * 2,
        input_snapshot={"shot_id": str(shot.id)},
        status="queued",
        created_by=user.id,
    )
    session.add(target)
    await session.flush()
    decisions = await evaluate_required_dependencies_many(session, runs=[target])
    assert decisions[target.id].action == expected
    target.input_snapshot = {"shot_id": str(uuid4())}
    await session.flush()
    missing = (await evaluate_required_dependencies_many(session, runs=[target]))[target.id]
    assert missing.error_code == "UPSTREAM_RUN_MISSING"


async def _required_target(env, source):
    _, session, user, project, shot = env
    node = GraphNode(
        graph_version_id=source.graph_version_id,
        node_key="video",
        node_type="video",
        display_name="Video",
        cacheable=True,
    )
    session.add(node)
    await session.flush()
    session.add(
        GraphEdge(
            graph_version_id=source.graph_version_id,
            upstream_node_id=source.graph_node_id,
            downstream_node_id=node.id,
            output_port="result",
            input_port="image",
            position=0,
            required=True,
        )
    )
    target = NodeRun(
        project_id=project.id,
        graph_version_id=source.graph_version_id,
        graph_node_id=node.id,
        attempt_no=1,
        idempotency_key=uuid4().hex,
        input_hash=uuid4().hex * 2,
        input_snapshot={"shot_id": str(shot.id)},
        status="queued",
        created_by=user.id,
    )
    session.add(target)
    await session.flush()
    return target


@pytest.mark.parametrize(
    "case", ["no-result", "missing-row", "missing-storage", "deleted", "foreign-project"]
)
async def test_batch_fails_closed_on_unavailable_or_foreign_artifacts(env, case):
    _, session, _, _, _ = env
    source = await add_run(env, "completed")
    target = await _required_target(env, source)
    artifact = await session.get(Artifact, source.result_artifact_id)
    assert artifact is not None
    if case == "no-result":
        source.result_artifact_id = None
    elif case == "missing-row":
        source.result_artifact_id = uuid4()
    elif case == "missing-storage":
        artifact.storage_state = "missing"
    elif case == "deleted":
        artifact.deleted_at = datetime.now(UTC)
    else:
        _, foreign_project, _, _, _ = await _seed(session)
        artifact.project_id = foreign_project.id
    if case != "no-result":
        await session.flush()
    # A transient ORM state must fail closed before flush; the database itself
    # also forbids persisting completed without a result Artifact.
    with session.no_autoflush:
        decision = (await evaluate_required_dependencies_many(session, runs=[target]))[target.id]
    assert decision.action == "fail"
    assert decision.error_code == "UPSTREAM_ARTIFACT_MISSING"


@pytest.mark.parametrize("status", ["blocked", "needs_human", "failed"])
async def test_batch_keeps_required_review_gate(env, status):
    _, session, _, _, _ = env
    source = await add_run(env, "completed")
    node = await session.get(GraphNode, source.graph_node_id)
    node.node_key = "identity_review"
    source.output_summary = {"status": status}
    target = await _required_target(env, source)
    decision = (await evaluate_required_dependencies_many(session, runs=[target]))[target.id]
    assert decision.action == "fail"
    assert decision.error_code == "UPSTREAM_TERMINAL_FAILURE"


async def test_summary_caps_current_failure_details(env):
    _, session, _, project, _ = env
    for index in range(25):
        run = await add_run(env, "failed", index + 1, shot_id=str(uuid4()))
        run.error_summary = "x" * 1000
    await session.flush()
    summary = await ProductionReadService(session).summary(project_id=project.id)
    assert summary.total_runs == summary.failed_runs == 25
    assert len(summary.recent_failures) == 20
    assert summary.has_more_failures is True
    assert all(len(run.error_summary) == 500 for run in summary.recent_failures)


async def test_audio_picker_pages_only_usable_project_audio_artifacts(env):
    _, session, _, project, _ = env
    _, foreign_project, _, _, _ = await _seed(session)
    expected = []
    for index in range(7):
        identity = uuid4()
        item = Artifact(
            id=identity,
            project_id=project.id,
            artifact_type="audio",
            object_key=f"audio/{identity}.wav",
            content_hash=identity.hex * 2,
            mime_type="audio/wav",
            byte_size=100,
            storage_state="available",
            created_at=datetime(2026, 9, 19, tzinfo=UTC),
        )
        session.add(item)
        if index < 3:
            expected.append(identity)
        elif index == 3:
            item.storage_state = "quarantined"
        elif index == 4:
            item.mime_type = "video/mp4"
        elif index == 5:
            item.deleted_at = datetime(2026, 9, 19, tzinfo=UTC)
        else:
            item.project_id = foreign_project.id
    await session.flush()
    service = ProductionReadService(session)
    first = await service.artifacts(project_id=project.id, limit=2, usable_audio=True)
    second = await service.artifacts(
        project_id=project.id, limit=2, cursor=first.next_cursor, usable_audio=True
    )
    assert first.next_cursor is not None
    assert second.next_cursor is None
    assert [a.id for page in [first, second] for a in page.items] == sorted(expected, reverse=True)
    assert all(
        a.mime_type.startswith("audio/") and a.storage_state == "available" for a in first.items
    )
    assert not session.new and not session.dirty
