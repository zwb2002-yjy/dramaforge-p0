"""CC10 — creative capability freeze + assistant context provenance."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.director.creative_capabilities.creative_compiler import CreativeCapabilityCompiler
from app.director.creative_capabilities.freeze import (
    freeze_scene_capabilities,
    freeze_shot_capabilities,
)
from app.director.creative_capabilities.packs_library import (
    GENRE_PROFILES,
    STYLE_PACKS,
)
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS
from app.shared.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed(session) -> tuple[Project, Scene, Shot]:
    user = User(email=f"cc10-{uuid4().hex[:8]}@example.com", display_name="U", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id, name=f"CC10-{uuid4().hex[:6]}", stage="draft",
        aspect_ratio="9:16", budget_limit=0,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id, scene_number=1, location_name="Street", time_of_day="night"
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id, scene_id=scene.id, shot_number=1, status="draft",
        visual_description="a person",
    )
    session.add(shot)
    await session.flush()
    return project, scene, shot


def _intent():
    compiler = CreativeCapabilityCompiler()
    return compiler.compile(
        genre=next(g for g in GENRE_PROFILES if g.genre_key == "short_drama_suspense_v1"),
        style=next(s for s in STYLE_PACKS if s.style_key == "film_noir_v1"),
        skill_stack=list(BASELINE_SKILLS[:2]),
    )


async def test_freeze_scene_writes_provenance(session) -> None:
    project, scene, shot = await _seed(session)
    await freeze_scene_capabilities(
        session, project_id=project.id, scene_id=scene.id, intent=_intent(), actor_id=uuid4()
    )
    await session.flush()
    got = await session.get(Scene, scene.id)
    assert got is not None
    froze = (got.design_state or {}).get("creative_capabilities")
    assert isinstance(froze, dict)
    assert froze["genre"]["key"] == "short_drama_suspense_v1"
    assert froze["style"]["key"] == "film_noir_v1"
    assert got.version == 2


async def test_freeze_shot_writes_provenance(session) -> None:
    project, scene, shot = await _seed(session)
    await freeze_shot_capabilities(
        session, project_id=project.id, shot_id=shot.id, intent=_intent(), actor_id=uuid4()
    )
    await session.flush()
    got = await session.get(Shot, shot.id)
    assert got is not None
    froze = (got.director_state or {}).get("creative_capabilities")
    assert isinstance(froze, dict)
    assert froze["skills"]
    assert got.version == 2


async def test_freeze_scene_rejects_cross_project(session) -> None:
    from app.shared.errors import ValidationAppError

    project, scene, shot = await _seed(session)
    other_user = User(
        email=f"cc10b-{uuid4().hex[:8]}@example.com", display_name="U2", password_hash="x"
    )
    session.add(other_user)
    await session.flush()
    other_workspace = Workspace(owner_user_id=other_user.id, name=f"W2-{uuid4().hex[:6]}")
    session.add(other_workspace)
    await session.flush()
    other_project = Project(
        workspace_id=other_workspace.id, name="other", stage="draft",
        aspect_ratio="9:16", budget_limit=0,
    )
    session.add(other_project)
    await session.flush()

    with pytest.raises(ValidationAppError):
        await freeze_scene_capabilities(
            session, project_id=other_project.id, scene_id=scene.id,
            intent=_intent(), actor_id=uuid4(),
        )
