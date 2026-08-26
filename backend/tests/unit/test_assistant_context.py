"""P7-03 Assistant context builder tests (03 §63)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Scene, Shot
from app.delivery.models import ReviewAnnotation
from app.director.assistant_context import AssistantContextBuilder
from app.director.models import DirectorMessage, DirectorThread
from app.production.models import ShotReferenceBinding
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
        email=f"ctx-{uuid4().hex}@example.com",
        display_name="Ctx",
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
    project.style_bible = {"palette": "teal", "tone": "cinematic"}
    from app.assets.models import Episode

    episode = Episode(
        project_id=project.id, episode_number=1, title="Episode 1",
    )
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id, scene_number=1,
        location_name="Studio", time_of_day="day",
        synopsis="Golden scene",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id, scene_id=scene.id, shot_number=1,
        version=2, visual_description="Shot", image_prompt="kf prompt",
        video_prompt="video prompt", director_state={"camera": "static"},
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


@pytest.mark.asyncio
async def test_context_reads_db_facts_and_messages(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    thread = DirectorThread(
        project_id=project.id, scope_type="shot", scope_entity_id=shot.id,
        created_by=user.id,
    )
    session.add(thread)
    await session.flush()
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    session.add(
        DirectorMessage(thread_id=thread.id, project_id=project.id, role="user",
                        content="建议改低机位", created_by=user.id, created_at=now)
    )
    await session.flush()
    session.add(
        DirectorMessage(thread_id=thread.id, project_id=project.id, role="assistant",
                        content="proposal v1", created_by=None,
                        created_at=now + timedelta(seconds=1))
    )
    await session.flush()
    session.add(
        ReviewAnnotation(
            project_id=project.id, shot_id=shot.id, created_by=user.id,
            time_start=2.3, time_end=3.1, note="人物漂移", severity="warning",
            status="open",
        )
    )
    session.add(
        ShotReferenceBinding(
            project_id=project.id, shot_id=shot.id, purpose="identity",
            asset_id=uuid4(), sort_order=1, created_by=user.id,
        )
    )
    await session.flush()

    ctx = await AssistantContextBuilder(session).build(
        project=project,
        thread=thread,
        current_user_message="再看看镜头",
    )
    assert ctx.project["visual_standard"]["palette"] == "teal"
    assert ctx.shot is not None
    assert ctx.shot["version"] == 2
    assert ctx.shot["director_state"]["camera"] == "static"
    assert len(ctx.shot["references"]) == 1
    assert len(ctx.open_annotations) == 1
    assert ctx.open_annotations[0]["note"] == "人物漂移"
    assert ctx.current_user_message == "再看看镜头"
    assert [m["role"] for m in ctx.recent_messages] == ["user", "assistant"]
    assert ctx.context_priority == "database_facts"


@pytest.mark.asyncio
async def test_context_scope_scene(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    thread = DirectorThread(
        project_id=project.id, scope_type="scene", scope_entity_id=shot.scene_id,
        created_by=user.id,
    )
    session.add(thread)
    await session.flush()
    ctx = await AssistantContextBuilder(session).build(
        project=project, thread=thread, current_user_message="hi"
    )
    assert ctx.scene is not None
    assert ctx.scene["location_name"] == "Studio"
    assert ctx.shot is None
