"""S3 NodeRun cache/stale and S5 export from Artifact rows."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.access import models as _a  # noqa: F401
from app.access.models import Workspace, User
from app.access.projects import ProjectService
from app.delivery.export_local import build_export_from_runs, build_export_package
from app.events import models as _e  # noqa: F401
from app.execution import models as _x  # noqa: F401
from app.execution.models import GraphNode
from app.execution.runtime_invariants import mark_stale_downstream, run_or_cache
from app.production import models as _p  # noqa: F401
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _project(session: AsyncSession) -> tuple[User, object]:
    user = User(
        email=f"u{uuid4().hex[:8]}@ex.com",
        display_name="U",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="O")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id, name=f"P{uuid4().hex[:6]}", aspect_ratio="9:16", actor=user
    )
    return user, project


@pytest.mark.asyncio
async def test_node_run_cache_hit_zero_cost(session: AsyncSession) -> None:
    user, project = await _project(session)
    g = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="shot-p0-v1",
        created_by=user.id,
    )
    assert g.current_version_id is not None
    node = GraphNode(
        graph_version_id=g.current_version_id,
        node_key="keyframe",
        node_type="keyframe",
        display_name="kf",
    )
    session.add(node)
    await session.flush()
    run1, budget = await run_or_cache(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node=node,
        input_hash="abc",
        created_by=user.id,
        budget_remaining=Decimal("10"),
        cost=Decimal("2"),
    )
    assert run1.status == "completed"
    assert run1.provider_cost == Decimal("2")
    run2, budget2 = await run_or_cache(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,
        graph_node=node,
        input_hash="abc",
        created_by=user.id,
        budget_remaining=budget,
        cost=Decimal("2"),
    )
    assert run2.status == "cached"
    assert run2.provider_cost == Decimal("0")
    assert run2.reused_from_run_id == run1.id
    assert run2.result_artifact_id == run1.result_artifact_id
    assert budget2 == Decimal("8")


def test_stale_downstream_from_subtitle() -> None:
    nodes = ["keyframe", "video", "voice", "subtitle", "composite"]
    edges = [
        ("keyframe", "video"),
        ("video", "composite"),
        ("voice", "composite"),
        ("subtitle", "composite"),
    ]
    stale = mark_stale_downstream(
        changed_node_key="subtitle", node_keys=nodes, edges=edges
    )
    assert "composite" in stale
    assert "keyframe" not in stale
    assert "video" not in stale


def test_export_package_hashes_stable() -> None:
    pid = uuid4()
    shots = [{"id": "1", "subtitle": "Hello"}, {"id": "2", "subtitle": "World"}]
    a = build_export_package(project_id=pid, shots=shots)
    b = build_export_package(project_id=pid, shots=shots)
    assert a.timeline_hash == b.timeline_hash
    assert a.srt_hash == b.srt_hash


@pytest.mark.asyncio
async def test_export_from_project_artifacts(session: AsyncSession) -> None:
    user, project = await _project(session)
    g = await GraphService(session).create_graph(
        project_id=project.id,
        scope_type="shot",
        scope_entity_id=uuid4(),
        template_key="shot-p0-v1",
        created_by=user.id,
    )
    node = GraphNode(
        graph_version_id=g.current_version_id,  # type: ignore[arg-type]
        node_key="composite",
        node_type="composite",
        display_name="c",
    )
    session.add(node)
    await session.flush()
    await run_or_cache(
        session,
        project_id=project.id,
        graph_version_id=g.current_version_id,  # type: ignore[arg-type]
        graph_node=node,
        input_hash="exp1",
        created_by=user.id,
        budget_remaining=Decimal("5"),
        cost=Decimal("1"),
    )
    await session.commit()
    pkg = await build_export_from_runs(
        session,
        project_id=project.id,
        shot_subtitles=[("s1", "Hi")],
    )
    assert len(pkg.source_artifact_ids) >= 1
    assert pkg.timeline_hash
