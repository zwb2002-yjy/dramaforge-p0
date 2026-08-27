"""WF5 — multi-character shot participation contract."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from app.access.models import User, Workspace
from app.assets.models import Asset, AssetVersion, Character
from app.director.workflows.character_participation import (
    DialogueRole,
    ScreenRole,
    ShotCharacterParticipation,
    ShotParticipationPlan,
    participation_director_state,
)
from app.director.workflows.participation_service import (
    validate_participation_bindings,
)
from app.shared.base import Base
from app.shared.errors import ValidationAppError
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
        email=f"wf5-{uuid4().hex[:8]}@example.com",
        display_name="U",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    from app.access.models import Project

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


async def _seed_character(
    session: AsyncSession, project_id: UUID, user_id: UUID, kind: str = "character"
) -> tuple[UUID, UUID]:
    asset = Asset(
        project_id=project_id,
        id=uuid4(),
        name=f"Char-{uuid4().hex[:6]}",
        kind=kind,
        status="ready",
    )
    session.add(asset)
    await session.flush()
    character = Character(id=asset.id, locked_prompt="lead", negative_prompt="")
    session.add(character)
    await session.flush()
    version = AssetVersion(
        project_id=project_id,
        asset_id=asset.id,
        version_number=1,
        kind=kind,
        name="v1",
        status="ready",
        created_by=user_id,
    )
    session.add(version)
    await session.flush()
    return asset.id, version.id


def _participation(
    character_id: UUID, asset_version_id: UUID, role: ScreenRole
) -> ShotCharacterParticipation:
    return ShotCharacterParticipation(
        character_id=character_id,
        asset_version_id=asset_version_id,
        screen_role=role,
        importance=80,
        dialogue_role=DialogueRole.SPEAKING,
        position="left",
        pose="three-quarter",
    )


@pytest.mark.asyncio
async def test_participation_plan_round_trip(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    char_a, ver_a = await _seed_character(session, project_id, user_id)
    plan = ShotParticipationPlan(
        participations=[_participation(char_a, ver_a, ScreenRole.PRIMARY)]
    )
    assert plan.visible_controlled_count == 1
    state = participation_director_state(plan)
    assert state["workflow_participations"][0]["character_id"] == str(char_a)
    assert state["max_visible_controlled_characters"] == 4


@pytest.mark.asyncio
async def test_participation_plan_rejects_more_than_4_visible(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    chars = [await _seed_character(session, project_id, user_id) for _ in range(5)]
    with pytest.raises(ValueError):
        ShotParticipationPlan(
            participations=[
                _participation(c[0], c[1], ScreenRole.SECONDARY) for c in chars
            ]
        )


@pytest.mark.asyncio
async def test_participation_plan_rejects_duplicate_character(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    char_a, ver_a = await _seed_character(session, project_id, user_id)
    with pytest.raises(ValueError):
        ShotParticipationPlan(
            participations=[
                _participation(char_a, ver_a, ScreenRole.PRIMARY),
                _participation(char_a, ver_a, ScreenRole.SECONDARY),
            ]
        )


@pytest.mark.asyncio
async def test_participation_plan_requires_identity_binding(session: AsyncSession) -> None:
    # A visible character without an identity asset version must fail.
    with pytest.raises(ValueError):
        ShotParticipationPlan(
            participations=[
                ShotCharacterParticipation(
                    character_id=uuid4(),
                    asset_version_id=None,
                    screen_role=ScreenRole.PRIMARY,
                )
            ]
        )


@pytest.mark.asyncio
async def test_validate_participation_bindings_ok(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    char_a, ver_a = await _seed_character(session, project_id, user_id)
    plan = ShotParticipationPlan(
        participations=[_participation(char_a, ver_a, ScreenRole.PRIMARY)]
    )
    await validate_participation_bindings(session, project_id=project_id, plan=plan)


@pytest.mark.asyncio
async def test_validate_participation_bindings_cross_workspace(session: AsyncSession) -> None:
    project_id, user_id = await _seed_project(session)
    char_a, ver_a = await _seed_character(session, project_id, user_id)
    plan = ShotParticipationPlan(
        participations=[_participation(char_a, ver_a, ScreenRole.PRIMARY)]
    )
    # Change only the project_id to simulate a cross-workspace reference.
    other_project, _ = await _seed_project(session)
    with pytest.raises(ValidationAppError) as excinfo:
        await validate_participation_bindings(
            session, project_id=other_project, plan=plan
        )
    assert excinfo.value.details.get("code") == "PARTICIPATION_ASSET_VERSION_CROSS_WORKSPACE"


@pytest.mark.asyncio
async def test_validate_participation_bindings_unknown_character(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    plan = ShotParticipationPlan(
        participations=[
            ShotCharacterParticipation(
                character_id=uuid4(),
                asset_version_id=None,
                screen_role=ScreenRole.OFFSCREEN,
            )
        ]
    )
    with pytest.raises(ValidationAppError) as excinfo:
        await validate_participation_bindings(session, project_id=project_id, plan=plan)
    assert excinfo.value.details.get("code") == "PARTICIPATION_CHARACTER_NOT_FOUND"
