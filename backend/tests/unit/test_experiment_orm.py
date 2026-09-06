"""P5-01 Experiment ORM tests (03 §45)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.production.models import ProductionExperiment, ShotExperiment
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
    shot = Shot(
        project_id=project.id,
        scene_id=uuid4(),
        shot_number=1,
        version=1,
        visual_description="Experiment shot",
    )
    session.add(shot)
    await session.flush()
    return project, shot, user


@pytest.mark.asyncio
async def test_experiment_round_trip_with_shot_experiments(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    experiment = ProductionExperiment(
        project_id=project.id,
        name="A/B model swap",
        idempotency_key=f"exp-{uuid4().hex}",
        experiment_type="model_swap",
        status="draft",
        created_by=user.id,
    )
    session.add(experiment)
    await session.flush()
    shot_exp = ShotExperiment(
        production_experiment_id=experiment.id,
        project_id=project.id,
        shot_id=shot.id,
        source_shot_version=1,
        director_state={"camera": "static"},
        prompts={"image_prompt": "keyframe A/B"},
        references=[{"purpose": "identity", "artifact_id": str(uuid4())}],
        model_overrides={"video.shot": "agnes/video-model-b"},
        common_controls={"aspect_ratio": "9:16"},
        status="draft",
        created_by=user.id,
    )
    session.add(shot_exp)
    await session.flush()

    rows = (
        await session.execute(
            select(ShotExperiment).where(ShotExperiment.production_experiment_id == experiment.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].model_overrides["video.shot"] == "agnes/video-model-b"
    assert rows[0].source_shot_version == 1
    assert rows[0].prompts["image_prompt"] == "keyframe A/B"


@pytest.mark.asyncio
async def test_experiment_idempotency_key_unique_per_project(session: AsyncSession) -> None:
    project, _shot, user = await _seed(session)
    key = f"exp-{uuid4().hex}"
    session.add(
        ProductionExperiment(
            project_id=project.id, name="a", idempotency_key=key, created_by=user.id
        )
    )
    await session.flush()
    session.add(
        ProductionExperiment(
            project_id=project.id, name="b", idempotency_key=key, created_by=user.id
        )
    )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_shot_experiment_unique_per_experiment_and_shot(session: AsyncSession) -> None:
    project, shot, user = await _seed(session)
    experiment = ProductionExperiment(
        project_id=project.id, name="x", idempotency_key=f"exp-{uuid4().hex}", created_by=user.id
    )
    session.add(experiment)
    await session.flush()
    session.add(
        ShotExperiment(
            production_experiment_id=experiment.id,
            project_id=project.id,
            shot_id=shot.id,
            created_by=user.id,
        )
    )
    await session.flush()
    session.add(
        ShotExperiment(
            production_experiment_id=experiment.id,
            project_id=project.id,
            shot_id=shot.id,
            created_by=user.id,
        )
    )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await session.flush()
