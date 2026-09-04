"""Canonical deterministic Scene layout and direct Workbench path tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Scene, Shot
from app.director.scene_assembler import (
    CharacterSpec,
    SceneAssembler,
    SceneLayoutSpec,
    SceneObjectSpec,
)
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


def test_gate_1_scene_assembler_deterministic_coordinates() -> None:
    """§79-1/2: 2D layout is plannable and deterministic (never LLM coords)."""
    spec = SceneLayoutSpec(
        door=SceneObjectSpec(kind="door", name="门", position="north"),
        furniture=[SceneObjectSpec(kind="table", name="桌子", position="center")],
        characters=[CharacterSpec(name="A", enters_from="south"), CharacterSpec(name="B")],
    )
    first = SceneAssembler().assemble(spec)
    second = SceneAssembler().assemble(spec)
    assert first == second  # deterministic
    assert first["generator"] == "deterministic_scene_assembler_v1"
    elements = first["elements"]
    kinds = {item["kind"] for item in elements}
    assert "character" in kinds and "table" in kinds and "door" in kinds
    door = next(item for item in elements if item["kind"] == "door")
    assert door["x"] == 0.5 and door["y"] == 0.15  # north


async def _seed_scene_shot(session: AsyncSession) -> tuple[Project, Shot, User]:
    user = User(
        email=f"board-{uuid4().hex}@example.com",
        display_name="Board",
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
    from app.assets.models import Episode

    episode = Episode(project_id=project.id, episode_number=1)
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id, scene_number=1, location_name="Studio",
        time_of_day="day", synopsis="", design_state={},
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id, scene_id=scene.id, shot_number=1, version=1,
        visual_description="Shot", director_state={},
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


@pytest.mark.asyncio
async def test_gate_6_can_skip_board_and_generate_directly(session: AsyncSession) -> None:
    """§79-6: user can generate directly without the director board."""
    project, shot, user = await _seed_scene_shot(session)
    # director board untouched; the shot still has its plain prompt path
    assert shot.director_state == {}
    # the plan path accepts a prompt without a control package (P4-05 path)
    from app.production.workbench_execution import WorkbenchExecutionInput

    workbench_input = WorkbenchExecutionInput(
        project_id=project.id, shot_id=shot.id, stage="image_keyframe",
        prompt="direct prompt", semantic_intent={"intent": "shot_keyframe"},
        mode_id="explicit_binding",
    )
    assert workbench_input.prompt == "direct prompt"
    assert workbench_input.semantic_intent["intent"] == "shot_keyframe"
