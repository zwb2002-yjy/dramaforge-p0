"""P7-04/05 Proposal ORM + typed commands tests (03 §64/§65)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Scene, Shot
from app.director.proposal_commands import (
    COMMAND_WHITELIST,
    ProposalCommandError,
    ProposalCommandRegistry,
)
from app.director.proposal_models import DirectorProposal, DirectorProposalItem
from app.production.models import ShotReferenceBinding
from app.shared.base import Base
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
        email=f"prop-{uuid4().hex}@example.com",
        display_name="Prop",
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
        episode_id=episode.id, scene_number=1, location_name="Studio", time_of_day="day",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id, scene_id=scene.id, shot_number=1, version=1,
        visual_description="Shot", image_prompt="kf", video_prompt="video",
        director_state={"camera": "static"},
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


def test_whitelist_contains_required_commands() -> None:
    required = {
        "shot.update_director_state",
        "shot.update_image_prompt",
        "shot.update_video_prompt",
        "shot.set_model_override",
        "shot_reference.add",
        "shot_reference.remove",
        "asset_version.promote",
        "scene.update_design",
        "experiment.create",
    }
    assert required.issubset(COMMAND_WHITELIST)


@pytest.mark.asyncio
async def test_unknown_command_rejected(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    assert not registry.is_known("raw_sql_execute")
    with pytest.raises(ProposalCommandError, match="unknown"):
        await registry.apply(
            project_id=project.id,
            command="raw_sql_execute",
            payload={"sql": "DROP TABLE shots"},
        )


@pytest.mark.asyncio
async def test_apply_shot_commands_with_version_check(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    await registry.apply(
        project_id=project.id,
        command="shot.update_director_state",
        payload={"shot_id": str(shot.id), "director_state": {"camera": "low"}},
        expected_target_version=1,
    )
    await session.refresh(shot)
    assert shot.director_state == {"camera": "low"}
    assert shot.version == 2
    # stale proposal rejected
    with pytest.raises(ProposalCommandError, match="stale"):
        await registry.apply(
            project_id=project.id,
            command="shot.update_image_prompt",
            payload={"shot_id": str(shot.id), "image_prompt": "x"},
            expected_target_version=1,
        )


@pytest.mark.asyncio
async def test_apply_reference_add(session: AsyncSession) -> None:
    from app.assets.models import Asset

    project, shot, user = await _seed(session)
    asset = Asset(project_id=project.id, kind="character", name="Lead")
    session.add(asset)
    await session.flush()
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    await registry.apply(
        project_id=project.id,
        command="shot_reference.add",
        payload={"shot_id": str(shot.id), "purpose": "identity", "asset_id": str(asset.id)},
    )
    rows = (
        await session.execute(
            select(ShotReferenceBinding).where(ShotReferenceBinding.shot_id == shot.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].purpose == "identity"


@pytest.mark.asyncio
async def test_proposal_item_persistence(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    proposal = DirectorProposal(
        project_id=project.id, thread_id=uuid4(), scope_type="shot",
        scope_entity_id=shot.id, status="pending", created_by=user.id,
    )
    session.add(proposal)
    await session.flush()
    item = DirectorProposalItem(
        proposal_id=proposal.id, project_id=project.id,
        command="shot.update_director_state",
        payload={"shot_id": str(shot.id), "director_state": {"camera": "low"}},
        expected_target_version=1,
        rationale="low camera for tension", status="pending",
    )
    session.add(item)
    await session.flush()
    rows = (
        await session.execute(
            select(DirectorProposalItem).where(
                DirectorProposalItem.proposal_id == proposal.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].command == "shot.update_director_state"
    assert rows[0].expected_target_version == 1


@pytest.mark.asyncio
async def test_scene_design_command_rechecks_scope_and_version(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    other, _, _ = await _seed(session)
    scene = await session.get(Scene, shot.scene_id)
    assert scene is not None
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    payload = {"scene_id": str(scene.id), "design_state": {"camera": "new"}}
    with pytest.raises(ProposalCommandError, match="not found"):
        await registry.apply(project_id=other.id, command="scene.update_design",
                             payload=payload, expected_target_version=scene.version)
    for stale in (None, scene.version + 1):
        with pytest.raises(ProposalCommandError, match="stale"):
            await registry.apply(project_id=project.id, command="scene.update_design",
                                 payload=payload, expected_target_version=stale)
    version = scene.version
    await registry.apply(project_id=project.id, command="scene.update_design",
                         payload=payload, expected_target_version=version)
    assert scene.design_state == {"camera": "new"}
    assert scene.version == version + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("command,kind", [
    ("shot.update_image_prompt", "shot"),
    ("story.upsert_episode", "episode"),
    ("story.upsert_scene", "scene"),
    ("story.upsert_shot", "shot"),
])
async def test_proposal_target_refreshes_before_version_check(session, command, kind):
    from app.assets.models import Episode
    from sqlalchemy import update

    project, shot, user = await _seed(session)
    scene = await session.get(Scene, shot.scene_id)
    episode = await session.get(Episode, scene.episode_id)
    target = {"shot": shot, "scene": scene, "episode": episode}[kind]
    await session.execute(update(type(target)).where(type(target).id == target.id)
        .values(version=2).execution_options(synchronize_session=False))
    assert target.version == 1
    with pytest.raises(ProposalCommandError, match="stale"):
        await ProposalCommandRegistry(session, actor_id=user.id).apply(
            project_id=project.id, command=command, expected_target_version=1,
            payload={"shot_id": str(shot.id), "episode_number": 1, "scene_number": 1,
                     "shot_number": 1, "image_prompt": "overwrite", "title": "overwrite"},
        )


@pytest.mark.asyncio
async def test_reference_command_rejects_foreign_asset(session):
    from app.assets.models import Asset
    project, shot, user = await _seed(session)
    other, _, _ = await _seed(session)
    foreign = Asset(project_id=other.id, kind="character", name="Foreign")
    session.add(foreign)
    await session.flush()
    with pytest.raises(ProposalCommandError, match="asset not found"):
        await ProposalCommandRegistry(session, actor_id=user.id).apply(
            project_id=project.id, command="shot_reference.add",
            payload={"shot_id": str(shot.id), "asset_id": str(foreign.id)},
        )


@pytest.mark.asyncio
async def test_reference_remove_rechecks_shot_scope(session):
    project, shot, user = await _seed(session)
    other = Shot(project_id=project.id, scene_id=shot.scene_id, shot_number=2,
                 visual_description="Other")
    binding = ShotReferenceBinding(project_id=project.id, shot_id=shot.id,
        purpose="identity", asset_id=uuid4(), created_by=user.id)
    session.add_all([other, binding])
    await session.flush()
    with pytest.raises(ProposalCommandError, match="binding not found"):
        await ProposalCommandRegistry(session, actor_id=user.id).apply(
            project_id=project.id, command="shot_reference.remove",
            payload={"shot_id": str(other.id), "binding_id": str(binding.id)},
        )
