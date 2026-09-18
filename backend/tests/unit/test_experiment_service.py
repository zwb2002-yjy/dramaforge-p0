"""Director and HTTP share the canonical experiment draft service."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Scene, Shot
from app.director.proposal_commands import (
    ProposalCommandError,
    ProposalCommandRegistry,
)
from app.execution.models import NodeRun
from app.production.archive_models import ProductionExperiment, ShotExperiment
from app.production.experiment_service import ExperimentCreateBody, create_experiment_branch
from app.production.models import ExperimentBranch
from app.shared.base import Base
from app.shared.errors import ConflictError, NotFoundError
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
        episode_id=episode.id,
        scene_number=1,
        location_name="Studio",
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
        visual_description="Shot",
        image_prompt="kf",
        video_prompt="video",
        director_state={"camera": "static"},
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["experiment.create", "shot.set_model_override"])
async def test_director_creates_only_canonical_draft(session: AsyncSession, command: str) -> None:
    project, shot, user = await _seed(session)
    registry = ProposalCommandRegistry(session, actor_id=user.id)
    payload = {"shot_id": str(shot.id), "model_overrides": {"video.shot": "agnes/model-b"}}
    await registry.apply(
        project_id=project.id, command=command, payload=payload, command_key="item-one"
    )
    await registry.apply(
        project_id=project.id, command=command, payload=payload, command_key="item-one"
    )
    branch = (await session.scalars(select(ExperimentBranch))).one()
    assert branch.source_shot_id == shot.id
    assert branch.selected_model == "agnes/model-b"
    assert branch.status == "draft"
    assert branch.parameters["target_node_key"] == "video"
    assert (await session.scalars(select(ProductionExperiment))).all() == []
    assert (await session.scalars(select(ShotExperiment))).all() == []
    assert (await session.scalars(select(NodeRun))).all() == []
    await session.refresh(shot)
    assert shot.version == 1
    assert shot.formal_keyframe_artifact_id is None
    assert shot.formal_video_artifact_id is None
    # Distinct proposal item identities do not conflate separate intentions.
    payload["model_overrides"] = {"video.shot": "agnes/model-c"}
    await registry.apply(
        project_id=project.id, command=command, payload=payload, command_key="item-two"
    )
    assert len((await session.scalars(select(ExperimentBranch))).all()) == 2


@pytest.mark.asyncio
async def test_canonical_director_payload_is_visible_in_context(session: AsyncSession) -> None:
    from app.director.assistant_context import AssistantContextBuilder
    from app.director.assistant_models import DirectorThread

    project, shot, user = await _seed(session)
    payload = {
        "source_shot_id": str(shot.id),
        "name": "Keyframe B",
        "idempotency_key": "keyframe-b",
        "selected_model": "agnes/image-b",
        "parameters": {"target_node_key": "keyframe"},
    }
    await ProposalCommandRegistry(session, actor_id=user.id).apply(
        project_id=project.id, command="experiment.create", payload=payload
    )
    branch = (await session.scalars(select(ExperimentBranch))).one()
    thread = DirectorThread(
        project_id=project.id, scope_type="shot", scope_entity_id=shot.id, created_by=user.id
    )
    session.add(thread)
    await session.flush()
    context = await AssistantContextBuilder(session).build(
        project=project, thread=thread, current_user_message="compare"
    )
    assert [row["experiment_id"] for row in context.experiments] == [str(branch.id)]
    assert context.experiments[0]["selected_model"] == "agnes/image-b"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"name": "different"},
        {"selected_model": "agnes/other"},
        {"parameters": {}},
        {"source_shot_id": None},
    ],
)
async def test_branch_idempotency_rejects_changed_inputs(
    session: AsyncSession, change: dict
) -> None:
    project, shot, user = await _seed(session)
    body = ExperimentCreateBody(
        source_shot_id=shot.id, name="B", idempotency_key="same", parameters={"purpose": "identity"}
    )
    row = await create_experiment_branch(
        session, project_id=project.id, actor_id=user.id, body=body
    )
    replay = await create_experiment_branch(
        session, project_id=project.id, actor_id=user.id, body=body
    )
    assert replay.id == row.id
    with pytest.raises(ConflictError):
        await create_experiment_branch(
            session, project_id=project.id, actor_id=user.id, body=body.model_copy(update=change)
        )


@pytest.mark.asyncio
async def test_branch_cannot_read_another_projects_shot(session: AsyncSession) -> None:
    project, _shot, user = await _seed(session)
    _other, foreign_shot, _owner = await _seed(session)
    with pytest.raises(NotFoundError):
        await create_experiment_branch(
            session,
            project_id=project.id,
            actor_id=user.id,
            body=ExperimentCreateBody(
                source_shot_id=foreign_shot.id, name="B", idempotency_key="foreign"
            ),
        )
    assert (await session.scalars(select(ExperimentBranch))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"shot_ids": []},
        {"shot_ids": [str(uuid4()), str(uuid4())]},
        {"model_overrides": {"video.shot": "a", "visual.keyframe": "b"}},
        {"model_overrides": {"unknown": "a"}},
        {"unexpected": "ignored?"},
    ],
)
async def test_ambiguous_director_payload_fails_closed(session: AsyncSession, extra: dict) -> None:
    project, shot, user = await _seed(session)
    with pytest.raises(ProposalCommandError):
        await ProposalCommandRegistry(session, actor_id=user.id).apply(
            project_id=project.id,
            command="experiment.create",
            payload={"shot_id": str(shot.id), **extra},
        )
    assert (await session.scalars(select(ExperimentBranch))).all() == []
