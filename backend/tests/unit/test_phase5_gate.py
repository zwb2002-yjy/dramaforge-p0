"""Phase 5 Gate tests (03 §51): six required proofs."""

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


async def _seed(session: AsyncSession) -> tuple[Project, User, list[Shot]]:
    user = User(
        email=f"gate-{uuid4().hex}@example.com",
        display_name="Gate",
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
    scene_id = uuid4()
    shots: list[Shot] = []
    for number in (1, 2):
        shot = Shot(
            project_id=project.id,
            scene_id=scene_id,
            shot_number=number,
            version=1,
            visual_description=f"Gate shot {number}",
            director_state={"camera": "static"},
            image_prompt=f"keyframe {number}",
            video_prompt=f"video {number}",
        )
        session.add(shot)
        await session.flush()
        shots.append(shot)
    return project, user, shots


async def _make_experiment(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    shot_ids: list,
    tag: str,
) -> ProductionExperiment:
    return await ExperimentService(session).create_experiment(
        project=project,
        actor=user,
        experiment_input=ExperimentCreateInput(
            name=f"gate-{tag}",
            shot_ids=shot_ids,
            model_overrides={"video.shot": f"model-{tag}"},
            idempotency_key=f"gate-{tag}-{uuid4().hex}",
        ),
    )


@pytest.mark.asyncio
async def test_gate_1_experiment_does_not_overwrite_formal(session: AsyncSession) -> None:
    project, user, _shots = await _seed(session)
    shot = _shots[0]
    original_version = shot.version
    await _make_experiment(session, project=project, user=user, shot_ids=[shot.id], tag="a")
    await session.refresh(shot)
    assert shot.version == original_version
    assert shot.image_prompt == "keyframe 1"
    assert shot.formal_keyframe_artifact_id is None


@pytest.mark.asyncio
async def test_gate_2_model_swap_does_not_copy_raw_payload(session: AsyncSession) -> None:

    project, user, _shots = await _seed(session)
    shot = _shots[0]
    experiment = await _make_experiment(
        session, project=project, user=user, shot_ids=[shot.id], tag="b"
    )
    shot_exp = (
        await session.execute(
            select(ShotExperiment).where(
                ShotExperiment.production_experiment_id == experiment.id
            )
        )
    ).scalars().one()
    # the snapshot only carries semantic inputs, never a provider raw payload
    snapshot = {
        "prompts": shot_exp.prompts,
        "references": shot_exp.references,
        "common_controls": shot_exp.common_controls,
        "model_overrides": shot_exp.model_overrides,
        "comparison": shot_exp.comparison,
    }
    assert "native_request" not in str(snapshot)
    assert "wire_request" not in str(snapshot)
    assert "authorization" not in str(snapshot).lower()
    assert "api_key" not in str(snapshot).lower()


@pytest.mark.asyncio
async def test_gate_3_ab_coexist(session: AsyncSession) -> None:
    project, user, _shots = await _seed(session)
    shot = _shots[0]
    experiment_a = await _make_experiment(
        session, project=project, user=user, shot_ids=[shot.id], tag="a"
    )
    experiment_b = await _make_experiment(
        session, project=project, user=user, shot_ids=[shot.id], tag="b"
    )
    rows = (
        await session.execute(
            select(ShotExperiment).where(ShotExperiment.shot_id == shot.id)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert {r.production_experiment_id for r in rows} == {experiment_a.id, experiment_b.id}


@pytest.mark.asyncio
async def test_gate_4_partial_adoption(session: AsyncSession) -> None:
    project, user, _shots = await _seed(session)
    shot = _shots[0]
    old_video = uuid4()
    shot.formal_video_artifact_id = old_video
    await session.flush()
    experiment = await _make_experiment(
        session, project=project, user=user, shot_ids=[shot.id], tag="a"
    )
    shot_exp = (
        await session.execute(
            select(ShotExperiment).where(
                ShotExperiment.production_experiment_id == experiment.id
            )
        )
    ).scalars().one()
    new_keyframe = uuid4()
    shot_exp.keyframe_artifact_id = new_keyframe
    shot_exp.video_artifact_id = uuid4()
    await session.flush()
    await ExperimentService(session).adopt_experiment(
        project=project,
        experiment_id=experiment.id,
        scope="keyframe_only",
    )
    await session.refresh(shot)
    assert shot.formal_keyframe_artifact_id == new_keyframe
    assert shot.formal_video_artifact_id == old_video  # video not adopted


@pytest.mark.asyncio
async def test_gate_5_old_formal_keeps_history_lineage(session: AsyncSession) -> None:
    project, user, _shots = await _seed(session)
    shot = _shots[0]
    old_keyframe = uuid4()
    old_video = uuid4()
    shot.formal_keyframe_artifact_id = old_keyframe
    shot.formal_video_artifact_id = old_video
    shot.version = 5
    await session.flush()
    experiment = await _make_experiment(
        session, project=project, user=user, shot_ids=[shot.id], tag="a"
    )
    shot_exp = (
        await session.execute(
            select(ShotExperiment).where(
                ShotExperiment.production_experiment_id == experiment.id
            )
        )
    ).scalars().one()
    new_keyframe = uuid4()
    shot_exp.keyframe_artifact_id = new_keyframe
    await session.flush()
    await ExperimentService(session).adopt_experiment(
        project=project,
        experiment_id=experiment.id,
        scope="keyframe_only",
    )
    await session.refresh(shot)
    # old formal results remain referenced (history lineage preserved) while the
    # formal keyframe advances to the experiment result
    assert shot.formal_video_artifact_id == old_video
    assert shot.formal_keyframe_artifact_id == new_keyframe
    # experiment snapshot still holds the source version for lineage
    assert shot_exp.source_shot_version == 5


@pytest.mark.asyncio
async def test_gate_6_scene_experiment_adopts_only_selected_shots(session: AsyncSession) -> None:
    project, user, (shot1, shot2) = await _seed(session)
    experiment = await _make_experiment(
        session, project=project, user=user, shot_ids=[shot1.id, shot2.id], tag="scene"
    )
    # adopt design for the whole experiment; then only shot1 gets keyframe
    shot_exps = (
        await session.execute(
            select(ShotExperiment).where(
                ShotExperiment.production_experiment_id == experiment.id
            )
        )
    ).scalars().all()
    kf1 = uuid4()
    for shot_exp in shot_exps:
        if shot_exp.shot_id == shot1.id:
            shot_exp.keyframe_artifact_id = kf1
    await session.flush()
    await ExperimentService(session).adopt_experiment(
        project=project,
        experiment_id=experiment.id,
        scope="keyframe_only",
    )
    await session.refresh(shot1)
    await session.refresh(shot2)
    assert shot1.formal_keyframe_artifact_id == kf1
    assert shot2.formal_keyframe_artifact_id is None
