"""Production read boundary: scoped, detached facts and fresh durable state."""

from uuid import uuid4

import pytest
from app.execution.models import NodeRun
from app.execution.shot_pipeline import SHOT_PIPELINE_TEMPLATE_KEY, shot_pipeline_definition
from app.production.application.facts import ProductionFacts
from app.production.service import GraphService
from app.shared.errors import ValidationAppError
from tests.unit.test_director_turn_service import _seed, session  # noqa: F401


async def _seed_execution(session):  # noqa: F811
    project, user, shot = await _seed(session)
    graphs = GraphService(session)
    graph = await graphs.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot.id,
        template_key=SHOT_PIPELINE_TEMPLATE_KEY,
        created_by=user.id,
        definition=shot_pipeline_definition(shot_id=str(shot.id)),
    )
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = await graphs.publish(version_id=materialized.version.id, published_by=user.id)
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=materialized.nodes["keyframe"].id,
        idempotency_key=f"read-fact:{uuid4().hex}",
        input_hash="a" * 64,
        status="running",
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    return project, user, shot, run


@pytest.mark.asyncio
async def test_read_fact_is_detached_and_does_not_expose_request_snapshot(session):  # noqa: F811
    project, _user, shot, run = await _seed_execution(session)
    reader = ProductionFacts(session)
    (before,) = await reader.executions(
        project_id=project.id, shot_id=shot.id, run_ids=(run.id,),
    )
    assert before.id == run.id and before.status == run.status
    assert not hasattr(before, "input_snapshot")
    run.status = "failed"
    await session.flush()
    (after,) = await reader.executions(
        project_id=project.id, shot_id=shot.id, run_ids=(run.id,),
    )
    assert after.status == "failed" and before.status != after.status


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_scope", ["project", "shot", "missing", "partial", "empty"])
async def test_read_fails_closed_for_unowned_or_incomplete_links(
    session, wrong_scope,  # noqa: F811
):
    project, _user, shot, run = await _seed_execution(session)
    ids = {"missing": (uuid4(),), "partial": (run.id, uuid4()), "empty": ()}
    with pytest.raises(ValidationAppError) as failure:
        await ProductionFacts(session).executions(
            project_id=uuid4() if wrong_scope == "project" else project.id,
            shot_id=uuid4() if wrong_scope == "shot" else shot.id,
            run_ids=ids.get(wrong_scope, (run.id,)),
        )
    assert failure.value.details["code"] == "PRODUCTION_EXECUTION_LINK_MISSING"
