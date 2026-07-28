"""S2 vertical: Graph → NodeRun → Fake Adapter → Artifact → face review."""

from __future__ import annotations

from uuid import UUID

import pytest
from app.access import models as _a  # noqa: F401
from app.access.models import Workspace, User
from app.access.projects import ProjectService
from app.events import models as _e  # noqa: F401
from app.execution import models as _x  # noqa: F401
from app.execution.models import Artifact, NodeRun, ProviderOperation
from app.execution.pipeline import (
    LEGACY_FIRST_FRAME_TEMPLATE_KEY,
    FirstFramePipeline,
    face_review_hook,
)
from app.production import models as _p  # noqa: F401
from app.production.models import GraphVersion, ProductionGraph
from app.shared.base import Base
from app.shared.errors import ValidationAppError
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


async def _seed_project(session: AsyncSession) -> tuple[User, UUID]:
    user = User(
        email="s2@example.com",
        display_name="S2",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name="S2Org")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name="S2Proj",
        aspect_ratio="9:16",
        actor=user,
    )
    return user, project.id


@pytest.mark.asyncio
async def test_first_frame_writes_graph_node_run_artifact(session: AsyncSession) -> None:
    user, project_id = await _seed_project(session)
    pipeline = FirstFramePipeline(session)
    result = await pipeline.run(
        project_id=project_id,
        user_id=user.id,
        idea="hero enters rain",
        authorized_text=True,
        authorized_image=True,
        materialization_ops=["create_shot_stub", "enqueue_keyframe"],
        face_threshold=0.35,
    )
    assert result.brief_text.startswith("BRIEF:")
    graph = await session.get(ProductionGraph, result.graph_id)
    assert graph is not None
    assert graph.template_key == LEGACY_FIRST_FRAME_TEMPLATE_KEY
    version = await session.get(GraphVersion, result.graph_version_id)
    assert version is not None
    run = await session.get(NodeRun, result.node_run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.result_artifact_id == result.artifact_id
    art = await session.get(Artifact, result.artifact_id)
    assert art is not None
    assert art.content_hash
    assert art.byte_size > 8
    assert art.object_key.startswith("projects/")
    ops = (
        (
            await session.execute(
                __import__("sqlalchemy")
                .select(ProviderOperation)
                .where(ProviderOperation.id.in_(result.provider_operation_ids))
            )
        )
        .scalars()
        .all()
    )
    # LEGACY spike records image ProviderOperation only (no forged AgentRun row).
    assert len(ops) == 1
    assert ops[0].actual_provider == "flux"
    # Two-source review status is real (not forced identity unit-vector pass)
    assert result.face_review.status in {"passed", "blocked", "warning", "needs_human"}
    assert run.output_summary is not None
    assert run.output_summary.get("embedding_source") == "probe_vs_canonical_images"


@pytest.mark.asyncio
async def test_first_frame_rejects_unauthorized(session: AsyncSession) -> None:
    user, project_id = await _seed_project(session)
    pipeline = FirstFramePipeline(session)
    with pytest.raises(ValidationAppError, match="TEXT_PROVIDER"):
        await pipeline.run(
            project_id=project_id,
            user_id=user.id,
            idea="x",
            authorized_text=False,
            authorized_image=True,
            materialization_ops=["enqueue_keyframe"],
        )


def test_face_review_hook_blocks_below_threshold() -> None:
    a = [0.0] * 512
    a[0] = 1.0
    b = [0.0] * 512
    b[1] = 1.0
    blocked = face_review_hook(embedding=a, canonical=b, threshold=0.5)
    assert blocked.status == "blocked"
