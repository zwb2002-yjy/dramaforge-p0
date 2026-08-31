"""P4-08 Keyframe formal selection tests (03 §38)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.execution.models import Artifact, NodeRun
from app.execution.shot_pipeline import (
    SHOT_PIPELINE_TEMPLATE_KEY,
    shot_pipeline_definition,
)
from app.production.formal_selection import (
    list_formal_candidates,
    require_formal_keyframe,
    set_formal_keyframe,
    set_formal_video,
)
from app.production.models import ProductionGraph
from app.production.service import GraphService
from app.shared.base import Base
from app.shared.errors import ValidationAppError
from app.shared.security import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _seed(session: AsyncSession) -> tuple[Project, Shot, User]:
    user = User(
        email=f"formal-{uuid4().hex}@example.com",
        display_name="Formal",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"P-{uuid4().hex[:8]}",
        aspect_ratio="9:16",
        actor=user,
    )
    shot = Shot(
        project_id=project.id,
        scene_id=uuid4(),
        shot_number=1,
        version=1,
        visual_description="A test shot",
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


async def _make_keyframe_artifact(
    session: AsyncSession,
    *,
    project: Project,
    shot_id,
    user: User,
    node_type: str = "keyframe",
    shot_scope: bool = True,
    run_status: str = "completed",
    artifact_type: str | None = None,
    snapshot_stage: str | None = None,
    attempt_no: int = 1,
) -> Artifact:
    graphs = GraphService(session)
    scope_type = "shot" if shot_scope else "episode"
    scope_entity_id = shot_id if shot_scope else uuid4()
    graph = await session.scalar(
        select(ProductionGraph).where(
            ProductionGraph.project_id == project.id,
            ProductionGraph.scope_type == scope_type,
            ProductionGraph.scope_entity_id == scope_entity_id,
        )
    )
    if graph is None:
        graph = await graphs.create_graph(
            project_id=project.id,
            scope_type=scope_type,
            scope_entity_id=scope_entity_id,
            template_key=SHOT_PIPELINE_TEMPLATE_KEY,
            created_by=user.id,
            definition=shot_pipeline_definition(shot_id=str(shot_id)),
        )
    assert graph.current_version_id is not None
    materialized = await graphs.materialize_definition(version_id=graph.current_version_id)
    version = materialized.version
    if version.status == "draft":
        version = await graphs.publish(version_id=version.id, published_by=user.id)
    node = (
        materialized.nodes["keyframe"]
        if node_type == "keyframe"
        else materialized.nodes["video"]
    )
    run = NodeRun(
        project_id=project.id,
        graph_version_id=version.id,
        graph_node_id=node.id,
        idempotency_key=f"keyframe:{uuid4().hex}",
        input_hash="a" * 64,
        attempt_no=attempt_no,
        status=run_status,
        input_snapshot={
            "shot_id": str(shot_id),
            "stage": snapshot_stage
            or ("image_keyframe" if node_type == "keyframe" else "video"),
        },
        created_by=user.id,
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type=artifact_type or ("video" if node_type == "video" else "image"),
        storage_state="stored",
        object_key=f"obj/{uuid4().hex}",
        content_hash=uuid4().hex * 2,
        mime_type="image/png",
        byte_size=1,
        produced_by_run_id=run.id,
    )
    session.add(artifact)
    await session.flush()
    run.result_artifact_id = artifact.id
    await session.flush()
    return artifact


@pytest.mark.asyncio
async def test_set_formal_keyframe_accepts_keyframe_artifact(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    artifact = await _make_keyframe_artifact(session, project=project, shot_id=shot.id, user=user)
    updated = await set_formal_keyframe(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        expected_shot_version=1,
    )
    assert updated.formal_keyframe_artifact_id == artifact.id
    assert updated.version == 2
    required = await require_formal_keyframe(
        session,
        project_id=project.id,
        shot_id=shot.id,
    )
    assert required.id == artifact.id


@pytest.mark.asyncio
async def test_set_formal_keyframe_rejects_non_keyframe_artifact(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    artifact = await _make_keyframe_artifact(
        session, project=project, shot_id=shot.id, user=user, node_type="video"
    )
    with pytest.raises(ValidationAppError, match="keyframe"):
        await set_formal_keyframe(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=artifact.id,
        )


@pytest.mark.asyncio
async def test_require_formal_keyframe_fails_closed_without_one(session: AsyncSession) -> None:
    project, shot, _user = await _seed(session)
    with pytest.raises(ValidationAppError, match="formal keyframe"):
        await require_formal_keyframe(
            session,
            project_id=project.id,
            shot_id=shot.id,
        )


@pytest.mark.asyncio
async def test_set_formal_keyframe_rejects_stale_expected_version(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    artifact = await _make_keyframe_artifact(session, project=project, shot_id=shot.id, user=user)
    with pytest.raises(ValidationAppError, match="concurrently") as caught:
        await set_formal_keyframe(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=artifact.id,
            expected_shot_version=99,
        )
    assert caught.value.status_code == 409
    assert caught.value.code == "CONFLICT"


@pytest.mark.asyncio
async def test_set_formal_video_accepts_video_artifact(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    artifact = await _make_keyframe_artifact(
        session, project=project, shot_id=shot.id, user=user, node_type="video"
    )
    updated = await set_formal_video(
        session,
        project_id=project.id,
        shot_id=shot.id,
        artifact_id=artifact.id,
        expected_shot_version=1,
    )
    assert updated.formal_video_artifact_id == artifact.id
    assert updated.version == 2


@pytest.mark.asyncio
async def test_set_formal_video_rejects_keyframe_artifact(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    artifact = await _make_keyframe_artifact(
        session, project=project, shot_id=shot.id, user=user, node_type="keyframe"
    )
    with pytest.raises(ValidationAppError, match="video"):
        await set_formal_video(
            session,
            project_id=project.id,
            shot_id=shot.id,
            artifact_id=artifact.id,
        )


@pytest.mark.asyncio
async def test_formal_selection_rejects_failed_running_wrong_type_and_stage(
    session: AsyncSession,
) -> None:
    project, shot, user = await _seed(session)
    failed = await _make_keyframe_artifact(
        session,
        project=project,
        shot_id=shot.id,
        user=user,
        run_status="failed",
    )
    running = await _make_keyframe_artifact(
        session,
        project=project,
        shot_id=shot.id,
        user=user,
        run_status="running",
        attempt_no=2,
    )
    wrong_type = await _make_keyframe_artifact(
        session,
        project=project,
        shot_id=shot.id,
        user=user,
        artifact_type="video",
        attempt_no=3,
    )
    wrong_stage = await _make_keyframe_artifact(
        session,
        project=project,
        shot_id=shot.id,
        user=user,
        snapshot_stage="video",
        attempt_no=4,
    )
    for artifact in (failed, running, wrong_type, wrong_stage):
        with pytest.raises(ValidationAppError, match="keyframe"):
            await set_formal_keyframe(
                session,
                project_id=project.id,
                shot_id=shot.id,
                artifact_id=artifact.id,
            )


@pytest.mark.asyncio
async def test_list_formal_candidates_returns_only_successful_real_artifacts(
    session: AsyncSession,
) -> None:
    project, shot, user = await _seed(session)
    accepted = await _make_keyframe_artifact(
        session, project=project, shot_id=shot.id, user=user
    )
    await _make_keyframe_artifact(
        session,
        project=project,
        shot_id=shot.id,
        user=user,
        run_status="failed",
        attempt_no=2,
    )
    candidates = await list_formal_candidates(
        session,
        project_id=project.id,
        shot_ids=[shot.id],
    )
    assert [row["artifact_id"] for row in candidates[shot.id]] == [accepted.id]
    assert candidates[shot.id][0]["stage"] == "image_keyframe"
