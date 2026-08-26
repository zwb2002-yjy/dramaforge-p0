"""P5-03 Experiment creation service tests (03 §47)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.production.experiment_service import (
    ExperimentCreateInput,
    ExperimentService,
)
from app.production.models import (
    ShotExperiment,
    ShotReferenceBinding,
)
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


async def _seed(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"exp-{uuid4().hex}@example.com",
        display_name="Exp",
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
    return project, user


async def _shot(
    session: AsyncSession,
    *,
    project: Project,
    scene_id=None,
    shot_number: int = 1,
) -> Shot:
    shot = Shot(
        project_id=project.id,
        scene_id=scene_id or uuid4(),
        shot_number=shot_number,
        version=3,
        visual_description="Shot",
        director_state={"camera": "static"},
        image_prompt="keyframe prompt",
        video_prompt="video prompt",
    )
    session.add(shot)
    await session.flush()
    return shot


@pytest.mark.asyncio
async def test_create_experiment_single_shot_snapshots_inputs(session: AsyncSession) -> None:
    project, user = await _seed(session)
    shot = await _shot(session, project=project)
    session.add(
        ShotReferenceBinding(
            project_id=project.id,
            shot_id=shot.id,
            purpose="identity",
            asset_id=uuid4(),
            sort_order=1,
            created_by=user.id,
        )
    )
    await session.flush()

    experiment = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(
            name="A/B",
            shot_ids=[shot.id],
            model_overrides={"video.shot": "agnes/model-b"},
            idempotency_key=f"exp-{uuid4().hex}",
        ),
    )
    shot_exp = (
        await session.execute(
            select(ShotExperiment).where(ShotExperiment.production_experiment_id == experiment.id)
        )
    ).scalars().one()
    assert shot_exp.source_shot_version == 3
    assert shot_exp.director_state == {"camera": "static"}
    assert shot_exp.prompts["image_prompt"] == "keyframe prompt"
    assert shot_exp.model_overrides["video.shot"] == "agnes/model-b"
    assert len(shot_exp.references) == 1
    assert shot_exp.references[0]["purpose"] == "identity"
    # formal shot untouched
    await session.refresh(shot)
    assert shot.version == 3


@pytest.mark.asyncio
async def test_create_experiment_scene_creates_all_shots(session: AsyncSession) -> None:
    project, user = await _seed(session)
    scene_id = uuid4()
    s1 = await _shot(session, project=project, scene_id=scene_id, shot_number=1)
    s2 = await _shot(session, project=project, scene_id=scene_id, shot_number=2)
    experiment = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(
            name="Scene A/B",
            scene_id=scene_id,
            idempotency_key=f"exp-{uuid4().hex}",
        ),
    )
    rows = (
        await session.execute(
            select(ShotExperiment).where(ShotExperiment.production_experiment_id == experiment.id)
        )
    ).scalars().all()
    assert {row.shot_id for row in rows} == {s1.id, s2.id}


@pytest.mark.asyncio
async def test_create_experiment_idempotent_and_requires_shots(session: AsyncSession) -> None:
    project, user = await _seed(session)
    shot = await _shot(session, project=project)
    key = f"exp-{uuid4().hex}"
    first = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(name="a", shot_ids=[shot.id], idempotency_key=key),
    )
    second = await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(name="b", shot_ids=[shot.id], idempotency_key=key),
    )
    assert first.id == second.id
    with pytest.raises(ValidationAppError, match="at least one shot"):
        await ExperimentService(session).create_experiment(
            project=project,
            actor=user,
            experiment_input=ExperimentCreateInput(
                name="c", shot_ids=[], idempotency_key=f"exp-{uuid4().hex}"
            ),
        )
