"""D5 per-Turn routing changes only explicitly new turns."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.config import Settings
from app.director.runtime.langgraph_adapter import ENGINE_VERSION, STATE_SCHEMA_VERSION
from app.director.runtime.routing import DirectorEngineRouter
from app.director.turn_models import DirectorTurn


def _turn() -> DirectorTurn:
    return DirectorTurn(
        id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        actor_id=uuid4(),
        scope_type="project",
        scope_entity_id=uuid4(),
        request_key=f"route:{uuid4()}",
        context_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_enabling_langgraph_does_not_rebind_existing_blank_turn() -> None:
    controls = AsyncMock()
    router = DirectorEngineRouter(
        settings=Settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url="postgresql://role:secret@db/app",
        ),
        controls=controls,
    )
    assert await router.bind_new(_turn(), created=False) is None
    controls.bind.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabled_new_turn_binds_exact_validated_engine_once() -> None:
    controls = AsyncMock()
    expected = object()
    controls.bind.return_value = expected
    turn = _turn()
    router = DirectorEngineRouter(
        settings=Settings(
            director_runtime_engine="langgraph",
            director_checkpoint_database_url="postgresql://role:secret@db/app",
        ),
        controls=controls,
    )
    assert await router.bind_new(turn, created=True) is expected
    controls.bind.assert_awaited_once_with(
        project_id=turn.project_id,
        turn_id=turn.id,
        engine_version=ENGINE_VERSION,
        state_schema_version=STATE_SCHEMA_VERSION,
    )


@pytest.mark.asyncio
async def test_rollback_keeps_an_already_bound_turn_on_langgraph() -> None:
    controls = AsyncMock()
    expected = object()
    controls.bind.return_value = expected
    turn = _turn()
    turn.engine_version = ENGINE_VERSION
    turn.state_schema_version = STATE_SCHEMA_VERSION
    turn.runtime_execution_id = uuid4()
    router = DirectorEngineRouter(settings=Settings(), controls=controls)
    assert await router.bind_new(turn, created=False) is expected
    assert router.engine_for(turn) == "langgraph"
