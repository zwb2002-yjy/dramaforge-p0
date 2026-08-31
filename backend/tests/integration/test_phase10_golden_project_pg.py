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
from decimal import Decimal
from uuid import uuid4

import pytest
from app.api.v1.opencut import opencut_manifest
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


@pytest.mark.asyncio
async def test_opencut_manifest_uses_formal_video_pointer_pg(pg_session: AsyncSession) -> None:
    """A successful video -> formal command -> GET manifest chain stays formal-only."""
    golden = await seed_golden_project(pg_session, suffix=uuid4().hex[:8])
    await set_rls_context(
        pg_session,
        user_id=golden.user.id,
        workspace_id=golden.workspace.id,
        project_id=golden.project.id,
    )
    assert golden.video is not None and golden.keyframe is not None
    shot = golden.shots[0]
    await pg_session.refresh(shot)
    assert shot.formal_video_artifact_id == golden.video.id

    # A newer successful result is only a candidate until the formal command
    # updates the Shot pointer; it must not displace the selected video.
    formal_run = await pg_session.get(NodeRun, golden.video.produced_by_run_id)
    assert formal_run is not None
    candidate_run_id = uuid4()
    candidate_artifact_id = uuid4()
    candidate_run = NodeRun(
        id=candidate_run_id,
        project_id=golden.project.id,
        graph_version_id=formal_run.graph_version_id,
        graph_node_id=formal_run.graph_node_id,
        attempt_no=2,
        idempotency_key=f"opencut-candidate-{uuid4().hex}",
        input_hash="c" * 64,
        status="completed",
        input_snapshot={"shot_id": str(shot.id), "stage": "video", "node_key": "video"},
        output_summary={"status": "completed"},
        result_artifact_id=candidate_artifact_id,
        created_by=golden.user.id,
    )
    candidate = Artifact(
        id=candidate_artifact_id,
        project_id=golden.project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"golden/{uuid4().hex}/candidate.mp4",
        content_hash="d" * 64,
        mime_type="video/mp4",
        byte_size=1024,
        duration_seconds=Decimal("5.000"),
        produced_by_run_id=candidate_run_id,
    )
    pg_session.add_all([candidate_run, candidate])
    await pg_session.flush()

    manifest = await opencut_manifest(golden.project.id, golden.user, pg_session)
    video_track = next(track for track in manifest.tracks if track.kind == "video")
    assert [clip.shot_id for clip in video_track.clips] == [shot.id]
    assert [clip.artifact_id for clip in video_track.clips] == [golden.video.id]
    assert golden.keyframe.id not in [clip.artifact_id for clip in video_track.clips]
    assert candidate.id not in [clip.artifact_id for clip in video_track.clips]
    assert video_track.clips[0].source_url == (
        f"/api/v1/projects/{golden.project.id}/artifacts/{golden.video.id}/content"
    )
