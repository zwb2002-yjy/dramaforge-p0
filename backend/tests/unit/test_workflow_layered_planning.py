"""WF8 — Episode/Scene layered planning."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Scene, Shot
from app.director.workflows.layered_planning import (
    EpisodePlanPayload,
    ProductionProfile,
    ScenePlanPayload,
    SceneStoryboardPlanPayload,
    ShotPlanPayload,
)
from app.director.workflows.layered_production_service import (
    materialize_episode_plan,
    materialize_scene_storyboard,
)
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


async def _seed_project(session: AsyncSession) -> tuple[UUID, UUID]:
    user = User(
        email=f"wf8-{uuid4().hex[:8]}@example.com",
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
    return project.id, user.id


def _episode_plan() -> EpisodePlanPayload:
    return EpisodePlanPayload(
        episode_number=1,
        title="Pilot",
        target_duration=90.0,
        story_goal="Introduce the world",
        opening_hook="A storm",
        turning_points=["Reveal"],
        ending_hook="Cliffhanger",
        production_profile=ProductionProfile.SHORT_DRAMA_EPISODE,
        scenes=[
            ScenePlanPayload(
                scene_number=1,
                location="Rainy street",
                time_of_day="night",
                scene_goal="Establish",
                estimated_duration=20.0,
            ),
            ScenePlanPayload(
                scene_number=2,
                location="Apartment",
                time_of_day="night",
                scene_goal="Dialog",
                estimated_duration=30.0,
            ),
        ],
    )


def test_episode_plan_rejects_too_few_scenes() -> None:
    with pytest.raises(ValueError):
        EpisodePlanPayload(
            episode_number=1,
            title="X",
            target_duration=60.0,
            scenes=[],
        )


def test_episode_plan_rejects_duplicate_scene_numbers() -> None:
    with pytest.raises(ValueError):
        EpisodePlanPayload(
            episode_number=1,
            title="X",
            target_duration=60.0,
            scenes=[
                ScenePlanPayload(
                    scene_number=1, location="A", time_of_day="day", estimated_duration=10
                ),
                ScenePlanPayload(
                    scene_number=1, location="B", time_of_day="day", estimated_duration=10
                ),
            ],
        )


def test_scene_storyboard_rejects_shot_count_and_duplicates() -> None:
    with pytest.raises(ValueError):
        SceneStoryboardPlanPayload(shots=[])
    with pytest.raises(ValueError):
        SceneStoryboardPlanPayload(
            shots=[
                ShotPlanPayload(shot_number=1, visual_description="a"),
                ShotPlanPayload(shot_number=1, visual_description="b"),
            ]
        )


@pytest.mark.asyncio
async def test_materialize_episode_plan_is_idempotent(session: AsyncSession) -> None:
    project_id, _ = await _seed_project(session)
    ep = await materialize_episode_plan(session, project_id=project_id, plan=_episode_plan())
    assert ep.id is not None
    scenes = list(
        (await session.execute(select(Scene).where(Scene.episode_id == ep.id))).scalars()
    )
    assert len(scenes) == 2

    # Re-materialize must not duplicate.
    ep2 = await materialize_episode_plan(session, project_id=project_id, plan=_episode_plan())
    assert ep2.id == ep.id
    scenes2 = list(
        (await session.execute(select(Scene).where(Scene.episode_id == ep.id))).scalars()
    )
    assert len(scenes2) == 2


@pytest.mark.asyncio
async def test_materialize_scene_storyboard_creates_shots(session: AsyncSession) -> None:
    project_id, _ = await _seed_project(session)
    ep = await materialize_episode_plan(session, project_id=project_id, plan=_episode_plan())
    scene = (
        await session.execute(select(Scene).where(Scene.episode_id == ep.id).limit(1))
    ).scalar_one()
    storyboard = SceneStoryboardPlanPayload(
        template_profile="two-character-dialogue-v1",
        shots=[
            ShotPlanPayload(
                shot_number=1,
                shot_type="medium",
                visual_description="A and B talk",
                duration_seconds=6.0,
                sort_order=1,
                template_key="two-character-dialogue-v1",
            ),
            ShotPlanPayload(
                shot_number=2,
                shot_type="close",
                visual_description="B reaction",
                duration_seconds=4.0,
                sort_order=2,
            ),
        ],
    )
    shots = await materialize_scene_storyboard(
        session, project_id=project_id, scene=scene, storyboard=storyboard
    )
    assert len(shots) == 2
    # Idempotent.
    shots2 = await materialize_scene_storyboard(
        session, project_id=project_id, scene=scene, storyboard=storyboard
    )
    assert len(shots2) == 2
    shot_rows = list(
        (await session.execute(select(Shot).where(Shot.scene_id == scene.id))).scalars()
    )
    assert len(shot_rows) == 2
    assert shot_rows[0].director_state.get("workflow_template_key") == "two-character-dialogue-v1"
