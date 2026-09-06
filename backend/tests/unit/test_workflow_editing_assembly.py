"""WF11 — long-form editing assembly (Episode -> Scene -> Shot timeline)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.editing.timeline_builder import build_edit_session_for_project
from app.execution.models import Artifact
from app.shared.base import Base
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_project(session: AsyncSession) -> UUID:
    user = User(
        email=f"wf11-{uuid4().hex[:8]}@example.com",
        display_name="U",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"Proj-{uuid4().hex[:6]}",
        stage="draft",
        aspect_ratio="9:16",
        budget_limit=0,
    )
    session.add(project)
    await session.flush()
    return project.id


async def _add_formal_shot(
    session: AsyncSession,
    *,
    project_id: UUID,
    episode_number: int,
    scene_number: int,
    shot_number: int,
    sort_order: int,
) -> None:
    episode = await session.scalar(
        select(Episode).where(
            Episode.project_id == project_id,
            Episode.episode_number == episode_number,
        )
    )
    if episode is None:
        episode = Episode(
            project_id=project_id,
            episode_number=episode_number,
            title=f"Ep {episode_number}",
            synopsis="",
        )
        session.add(episode)
        await session.flush()
    scene = await session.scalar(
        select(Scene).where(
            Scene.episode_id == episode.id,
            Scene.scene_number == scene_number,
        )
    )
    if scene is None:
        scene = Scene(
            episode_id=episode.id,
            scene_number=scene_number,
            location_name="Room",
            time_of_day="night",
            synopsis="",
        )
        session.add(scene)
        await session.flush()
    artifact = Artifact(
        project_id=project_id,
        artifact_type="video",
        storage_state="ready",
        object_key=f"proj/{project_id}/video-{episode_number}-{scene_number}-{shot_number}.mp4",
        content_hash=uuid4().hex,
        mime_type="video/mp4",
        byte_size=1,
        duration_seconds=Decimal("6"),
    )
    session.add(artifact)
    await session.flush()
    shot = Shot(
        id=uuid4(),
        project_id=project_id,
        scene_id=scene.id,
        shot_number=shot_number,
        shot_type="medium",
        camera_move="static",
        visual_description="v",
        dialogue="",
        duration_seconds=Decimal("6"),
        status="complete",
        sort_order=sort_order,
        formal_video_artifact_id=artifact.id,
    )
    session.add(shot)
    await session.flush()


@pytest.mark.asyncio
async def test_edit_session_assembles_episode_scene_shot_order(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    # Episode 2 scene 1 comes after Episode 1 scene 2 in the timeline.
    await _add_formal_shot(
        session,
        project_id=project_id,
        episode_number=1,
        scene_number=2,
        shot_number=1,
        sort_order=1,
    )
    await _add_formal_shot(
        session,
        project_id=project_id,
        episode_number=2,
        scene_number=1,
        shot_number=1,
        sort_order=1,
    )
    await _add_formal_shot(
        session,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        shot_number=1,
        sort_order=1,
    )
    result = await build_edit_session_for_project(
        session, project_id=project_id, user_id=uuid4(), name="Long-form"
    )
    clips = result["clips"]
    assert len(clips) == 3
    # Ordered by episode_number, then scene_number.
    assert [clip["episode_number"] for clip in clips] == [1, 1, 2]
    assert [clip["scene_number"] for clip in clips] == [1, 2, 1]
    assert [clip["order"] for clip in clips] == [1, 2, 3]
    # Every clip keeps its hierarchy + artifact lineage.
    for clip in clips:
        assert "episode_id" in clip
        assert "scene_id" in clip
        assert "shot_id" in clip
        assert "artifact_id" in clip
    assert result["production_lineage"]["lineage_readonly"] is True
