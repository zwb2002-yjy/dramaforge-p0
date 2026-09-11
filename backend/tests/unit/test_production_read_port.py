"""Production read boundary: scoped, detached facts and fresh durable state."""

from uuid import uuid4

import pytest
from app.production.application.facts import ProductionFacts
from app.shared.errors import ValidationAppError
from tests.unit.test_director_next_action import _seed, session  # noqa: F401


@pytest.mark.asyncio
async def test_read_fact_is_detached_and_does_not_expose_request_snapshot(session):  # noqa: F811
    project, _user, shot, run, _turn = await _seed(session)
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
    project, _user, shot, run, _turn = await _seed(session)
    ids = {"missing": (uuid4(),), "partial": (run.id, uuid4()), "empty": ()}
    with pytest.raises(ValidationAppError) as failure:
        await ProductionFacts(session).executions(
            project_id=uuid4() if wrong_scope == "project" else project.id,
            shot_id=uuid4() if wrong_scope == "shot" else shot.id,
            run_ids=ids.get(wrong_scope, (run.id,)),
        )
    assert failure.value.details["code"] == "PRODUCTION_EXECUTION_LINK_MISSING"
