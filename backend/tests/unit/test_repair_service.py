"""P6-04/05/06 Manual repair service tests (03 §56-58)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Episode, Scene, Shot
from app.delivery.models import ReviewAnnotation
from app.production.repair_service import RepairService
from app.shared.base import Base
from app.shared.security import hash_password
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
        email=f"repair-{uuid4().hex}@example.com",
        display_name="Repair",
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
    from app.execution.models import Artifact

    formal_keyframe = Artifact(
        project_id=project.id,
        artifact_type="image",
        storage_state="stored",
        object_key=f"obj/{uuid4().hex}",
        content_hash="f" * 64,
        mime_type="image/png",
        byte_size=1,
    )
    session.add(formal_keyframe)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Repair studio",
        time_of_day="day",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=1,
        version=1,
        visual_description="Repair shot",
        image_prompt="keyframe prompt",
        video_prompt="video prompt",
        formal_keyframe_artifact_id=formal_keyframe.id,
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


@pytest.mark.asyncio
async def test_repair_plan_with_video_range_suggests_regenerate(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    session.add(
        ReviewAnnotation(
            project_id=project.id,
            shot_id=shot.id,
            created_by=user.id,
            time_start=2.3,
            time_end=3.1,
            note="人物漂移",
            severity="warning",
            status="open",
        )
    )
    await session.flush()
    plan = await RepairService(session).build_repair_plan(project=project, shot_id=shot.id)
    assert plan.suggested_option == "regenerate_keyframe_then_video"
    assert plan.affected_nodes == ["keyframe", "video"]
    assert plan.annotation_count == 1


@pytest.mark.asyncio
async def test_repair_plan_region_suggests_rerun_video(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    session.add(
        ReviewAnnotation(
            project_id=project.id,
            shot_id=shot.id,
            created_by=user.id,
            x=0.2,
            y=0.3,
            width=0.4,
            height=0.2,
            note="色偏",
            severity="warning",
            status="open",
        )
    )
    await session.flush()
    plan = await RepairService(session).build_repair_plan(project=project, shot_id=shot.id)
    assert plan.suggested_option == "rerun_video"
    assert plan.affected_nodes == ["video"]
    assert "formal_keyframe" in plan.retained_assets
