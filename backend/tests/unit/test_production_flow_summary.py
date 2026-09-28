"""The visible production flow reads exact, bounded mainline execution facts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.execution.models import GraphNode, NodeRun
from app.execution.shot_pipeline import SHOT_NODES
from app.production.read_service import ProductionReadService
from sqlalchemy import event
from tests.unit.test_production_bounded_reads import add_run
from tests.unit.test_scene_workspace_snapshot import _make_env, _seed


@pytest.fixture
async def env():
    engine, session = await _make_env()
    user, project, _, _, shot = await _seed(session)
    yield engine, session, user, project, shot
    await session.close()
    await engine.dispose()


async def test_flow_stages_exist_without_fabricating_completed_work(env):
    _, session, _, project, _ = env
    result = await ProductionReadService(session).summary(project_id=project.id)
    assert [stage.node_key for stage in result.stages] == list(SHOT_NODES)
    assert all(stage.status_counts == {} for stage in result.stages)
    assert all(stage.latest_failure is None for stage in result.stages)


async def test_flow_excludes_experiments_and_old_attempts_from_mainline(env):
    _, session, _, project, _ = env
    await add_run(env, "failed", 1)
    await add_run(env, "completed", 2)
    await add_run(env, "failed", 3, execution_branch="experiment", experiment_id="variant-a")
    await add_run(env, "running", 4, experiment_id="variant-b")
    result = await ProductionReadService(session).summary(project_id=project.id)
    stages = {stage.node_key: stage for stage in result.stages}
    assert stages["keyframe"].status_counts == {"completed": 1}
    assert stages["keyframe"].latest_failure is None
    assert stages["video"].status_counts == {}
    assert result.failed_runs == 1  # Resource totals still include the explicit experiment.


async def test_each_stage_retains_its_failure_even_beyond_recent_failure_limit(env):
    engine, session, user, project, shot = env
    keyframe = await add_run(env, "failed", 1)
    start = datetime(2026, 9, 19, tzinfo=UTC)
    keyframe.created_at = start
    keyframe.error_code = "MODEL_BINDING_MISSING"
    keyframe.error_summary = "Missing keyframe binding"
    video = GraphNode(
        graph_version_id=keyframe.graph_version_id,
        node_key="video",
        node_type="video",
        display_name="Video",
        cacheable=True,
    )
    unrelated = GraphNode(
        graph_version_id=keyframe.graph_version_id,
        node_key="not_a_video_stage",
        node_type="video",
        display_name="Unrelated custom step",
        cacheable=True,
    )
    session.add_all([video, unrelated])
    await session.flush()
    last_video = None
    for index in range(30):
        last_video = NodeRun(
            project_id=project.id,
            graph_version_id=keyframe.graph_version_id,
            graph_node_id=video.id,
            attempt_no=index + 1,
            idempotency_key=uuid4().hex,
            input_hash=uuid4().hex * 2,
            input_snapshot={"shot_id": str(uuid4()), "frozen_prompt": "private" * 1000},
            status="failed",
            error_code="UPSTREAM_ARTIFACT_MISSING",
            error_summary="Missing formal keyframe " + "x" * 1000,
            created_by=user.id,
            created_at=start + timedelta(seconds=index + 1),
        )
        session.add(last_video)
    session.add(
        NodeRun(
            project_id=project.id,
            graph_version_id=keyframe.graph_version_id,
            graph_node_id=unrelated.id,
            attempt_no=1,
            idempotency_key=uuid4().hex,
            input_hash=uuid4().hex * 2,
            input_snapshot={"shot_id": str(shot.id)},
            status="running",
            created_by=user.id,
        )
    )
    await session.flush()
    statements = []

    def record(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        result = await ProductionReadService(session).summary(project_id=project.id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert len(statements) == 4
    assert len(result.recent_failures) == 20
    assert keyframe.id not in {run.id for run in result.recent_failures}
    stages = {stage.node_key: stage for stage in result.stages}
    assert stages["keyframe"].status_counts == {"failed": 1}
    assert stages["keyframe"].latest_failure.id == keyframe.id
    assert stages["video"].status_counts == {"failed": 30}
    assert stages["video"].latest_failure.id == last_video.id
    assert len(stages["video"].latest_failure.error_summary) == 500
    assert "frozen_prompt" not in result.model_dump_json()
    assert len(result.stages) == 9
    foreign = await ProductionReadService(session).summary(project_id=uuid4())
    assert all(
        stage.status_counts == {} and stage.latest_failure is None for stage in foreign.stages
    )
