"""Phase 10 P10-06 Golden Professional Project verification on real PG.

Seeds the deterministic golden acceptance project and asserts every P10-06
requirement (plan 03 §93): script, 2+ scenes, one lead character with 2+
canonical reference angles, scene assets, multiple shots, formal keyframe +
video, experiments, review repair, Director Proposal, 2D director board,
editing, and export — all present and readable.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from app.assets.models import Character, CharacterReference
from app.delivery.models import Export
from app.director.models import DirectorMessage, DirectorThread
from app.director.proposal_models import DirectorProposalItem
from app.editing.models import EditSession
from app.execution.models import Artifact, NodeRun
from app.production.golden_project import seed_golden_project
from app.production.models import ProductionExperiment, ShotExperiment
from app.shared.db import set_rls_context
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_URL = "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def _postgres_is_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=1.0):
            pass
        sync_url = _database_url().replace("postgresql+asyncpg://", "postgresql+psycopg://")
        from sqlalchemy import create_engine

        engine = create_engine(sync_url, connect_args={"connect_timeout": 2})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_PG_ENABLED") != "1" or not _postgres_is_available(),
    reason="set TEST_PG_ENABLED=1 with an explicitly configured PostgreSQL target",
)


@pytest.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_golden_professional_project_covers_p10_06_pg(pg_session: AsyncSession) -> None:
    golden = await seed_golden_project(pg_session, suffix=uuid4().hex[:8])
    await set_rls_context(
        pg_session,
        user_id=golden.user.id,
        workspace_id=golden.workspace.id,
        project_id=golden.project.id,
    )

    # Script + 2+ scenes + multiple shots.
    assert len(golden.scenes) >= 2
    assert len(golden.shots) >= 2

    # One lead character with 2+ canonical reference angles.
    lead = await pg_session.get(Character, golden.lead.id)
    assert lead is not None
    refs = (
        (
            await pg_session.execute(
                select(CharacterReference).where(CharacterReference.character_id == lead.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(refs) >= 2 and all(ref.is_canonical for ref in refs)

    # Scene assets.
    assert len(golden.scene_assets) >= 2

    # Formal keyframe + video (readable, and shot points at them).
    keyframe = await pg_session.get(Artifact, golden.keyframe.id)
    video = await pg_session.get(Artifact, golden.video.id)
    assert keyframe is not None and video is not None
    shot_one = golden.shots[0]
    await pg_session.refresh(shot_one)
    assert shot_one.formal_keyframe_artifact_id == golden.keyframe.id
    assert shot_one.formal_video_artifact_id == golden.video.id

    # NodeRuns completed for keyframe/video.
    runs = (
        (await pg_session.execute(select(NodeRun).where(NodeRun.project_id == golden.project.id)))
        .scalars()
        .all()
    )
    assert len(runs) >= 2

    # Experiment branch.
    experiment = await pg_session.get(ProductionExperiment, golden.experiment.id)
    assert experiment is not None
    shot_experiments = (
        (
            await pg_session.execute(
                select(ShotExperiment).where(ShotExperiment.project_id == golden.project.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(shot_experiments) >= 1

    # Review + repair.
    assert golden.open_annotation is not None and golden.open_annotation.status == "open"
    assert (
        golden.resolved_annotation is not None and golden.resolved_annotation.status == "resolved"
    )
    assert golden.repair_suggested in {"rerun_video", "regenerate_keyframe_then_video"}

    # Director Proposal.
    assert golden.proposal is not None
    items = (
        (
            await pg_session.execute(
                select(DirectorProposalItem).where(
                    DirectorProposalItem.proposal_id == golden.proposal.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(items) >= 1
    thread = await pg_session.get(DirectorThread, golden.proposal.thread_id)
    assert thread is not None
    messages = (
        (
            await pg_session.execute(
                select(DirectorMessage).where(DirectorMessage.thread_id == thread.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(messages) >= 1

    # 2D director board on scene 1 + shot director_state.
    scene_one = golden.scenes[0]
    await pg_session.refresh(scene_one)
    assert scene_one.design_state.get("blocking_2d")
    await pg_session.refresh(shot_one)
    assert shot_one.director_state

    # Edit session.
    edit = await pg_session.get(EditSession, golden.edit_session_id)
    assert edit is not None and edit.project_id == golden.project.id
    assert edit.timeline.get("clips")

    # Export.
    export = await pg_session.get(Export, golden.export.id)
    assert export is not None and export.status == "completed"
