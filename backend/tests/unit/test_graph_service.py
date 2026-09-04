"""Graph definition validation, materialization, and publish-boundary tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import User, Workspace
from app.access.projects import ProjectService
from app.execution.models import GraphEdge, GraphNode
from app.production import models as _production_models  # noqa: F401
from app.production.models import GraphVersion
from app.production.service import GraphService, validate_graph_definition
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


def _definition() -> dict[str, object]:
    return {
        "nodes": [
            {"key": "prompt", "type": "prompt_compose"},
            {"key": "keyframe", "type": "keyframe"},
            {"key": "video", "type": "video"},
        ],
        "edges": [
            ["prompt", "keyframe"],
            ["keyframe", "video"],
        ],
    }


@pytest.mark.parametrize(
    "definition",
    [
        {
            "nodes": ["a", "b"],
            "edges": [["a", "b"], ["b", "a"]],
        },
        {
            "nodes": ["a"],
            "edges": [["a", "missing"]],
        },
        {
            "nodes": [{"key": "a", "type": "prompt"}, {"key": "a", "type": "video"}],
            "edges": [],
        },
        {
            "nodes": ["a", "b", "c"],
            "edges": [
                {"upstream": "a", "downstream": "c", "input_port": "input", "position": 0},
                {"upstream": "b", "downstream": "c", "input_port": "input", "position": 0},
            ],
        },
    ],
)
def test_invalid_graph_definitions_fail_closed(definition: dict[str, object]) -> None:
    with pytest.raises(ValidationAppError):
        validate_graph_definition(definition)


async def _project(session: AsyncSession) -> tuple[User, object]:
    user = User(
        email=f"graph-{uuid4().hex[:8]}@example.com",
        display_name="Graph",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"Graph-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"Graph-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        actor=user,
    )
    return user, project


@pytest.mark.asyncio
async def test_graph_materialization_is_idempotent_and_publish_checks_hash(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    service = GraphService(session)
    graph = await service.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="test-graph",
        created_by=user.id,
        definition=_definition(),
    )
    assert graph.current_version_id is not None
    first = await service.materialize_definition(version_id=graph.current_version_id)
    second = await service.materialize_definition(version_id=graph.current_version_id)
    node_count = await session.scalar(
        select(func.count()).select_from(GraphNode).where(
            GraphNode.graph_version_id == graph.current_version_id
        )
    )
    edge_count = await session.scalar(
        select(func.count()).select_from(GraphEdge).where(
            GraphEdge.graph_version_id == graph.current_version_id
        )
    )
    assert len(first.nodes) == len(second.nodes) == 3
    assert len(first.edges) == len(second.edges) == 2
    assert node_count == 3
    assert edge_count == 2

    version = await session.get(GraphVersion, graph.current_version_id)
    assert version is not None
    version.definition = {**version.definition, "extra": "tampered"}
    with pytest.raises(ValidationAppError, match="hash"):
        await service.publish(version_id=version.id, published_by=user.id)


@pytest.mark.asyncio
async def test_published_graph_relation_mismatch_is_not_repaired(
    session: AsyncSession,
) -> None:
    user, project = await _project(session)
    service = GraphService(session)
    graph = await service.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="test-graph",
        created_by=user.id,
        definition=_definition(),
    )
    assert graph.current_version_id is not None
    await service.publish(version_id=graph.current_version_id, published_by=user.id)
    edge = await session.scalar(
        select(GraphEdge).where(GraphEdge.graph_version_id == graph.current_version_id)
    )
    assert edge is not None
    await session.delete(edge)
    await session.flush()
    with pytest.raises(ValidationAppError, match="published graph edges"):
        await service.materialize_definition(version_id=graph.current_version_id)


@pytest.mark.asyncio
async def test_shot_pipeline_graph_round_trip(session: AsyncSession) -> None:
    """P4-06: scope_type=shot + SHOT_PIPELINE_TEMPLATE_KEY round-trips and
    publishes nodes keyframe/video (reuses the existing Shot Pipeline)."""
    from app.execution.shot_pipeline import (
        SHOT_PIPELINE_TEMPLATE_KEY,
        shot_pipeline_definition,
    )

    user, project = await _project(session)
    service = GraphService(session)
    shot_id = uuid4()
    graph = await service.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key=SHOT_PIPELINE_TEMPLATE_KEY,
        created_by=user.id,
        definition=shot_pipeline_definition(shot_id=str(shot_id)),
    )
    assert graph.scope_type == "shot"
    assert graph.scope_entity_id == shot_id
    assert graph.template_key == SHOT_PIPELINE_TEMPLATE_KEY
    assert graph.current_version_id is not None
    materialized = await service.materialize_definition(version_id=graph.current_version_id)
    version = await service.publish(version_id=materialized.version.id, published_by=user.id)
    assert version.status == "published"
    assert "keyframe" in materialized.nodes
    assert "video" in materialized.nodes
    assert materialized.nodes["keyframe"].node_type == "keyframe"
    assert materialized.nodes["video"].node_type == "video"


@pytest.mark.asyncio
async def test_graph_rejects_invalid_scope(session: AsyncSession) -> None:
    user, project = await _project(session)
    service = GraphService(session)
    with pytest.raises(ValidationAppError, match="scope_type"):
        await service.create_graph(
            project_id=project.id,
            scope_type="unknown",
            scope_entity_id=uuid4(),
            template_key="t",
            created_by=user.id,
        )


@pytest.mark.asyncio
async def test_shot_experiment_graph_independent_from_formal(session: AsyncSession) -> None:
    """P5-02: formal shot graph A and shot_experiment graph B are independent;
    publishing B does not change A.current_version."""
    user, project = await _project(session)
    service = GraphService(session)
    shot_id = uuid4()
    graph_a = await service.create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=shot_id,
        template_key="formal-shot",
        created_by=user.id,
        definition=_definition(),
    )
    assert graph_a.current_version_id is not None
    mat_a = await service.materialize_definition(version_id=graph_a.current_version_id)
    await service.publish(version_id=mat_a.version.id, published_by=user.id)
    a_version_before = graph_a.current_version_id
    a_status_before = (
        await session.get(GraphVersion, graph_a.current_version_id)
    ).status

    experiment_id = uuid4()
    graph_b = await service.create_graph(
        project_id=project.id,
        scope_type="shot_experiment",
        scope_entity_id=experiment_id,
        template_key="shot-experiment",
        created_by=user.id,
        definition=_definition(),
    )
    assert graph_b.current_version_id is not None
    assert graph_b.id != graph_a.id
    mat_b = await service.materialize_definition(version_id=graph_b.current_version_id)
    await service.publish(version_id=mat_b.version.id, published_by=user.id)

    # A is untouched
    await session.refresh(graph_a)
    assert graph_a.current_version_id == a_version_before
    a_status_after = (await session.get(GraphVersion, graph_a.current_version_id)).status
    assert a_status_after == a_status_before
    # B is its own published graph
    assert graph_b.scope_type == "shot_experiment"
    assert graph_b.scope_entity_id == experiment_id
