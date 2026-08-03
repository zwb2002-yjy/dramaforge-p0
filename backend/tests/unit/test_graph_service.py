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
