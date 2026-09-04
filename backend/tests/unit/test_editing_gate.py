"""Phase 9 Gate tests (03 §86): timeline -> edit -> save -> reopen -> export; lineage."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.assets.models import Shot
from app.editing.adapter import EditingAdapter
from app.editing.timeline_builder import build_edit_session_from_shots
from app.execution.models import Artifact
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


async def _seed(session: AsyncSession) -> tuple[Project, list[Shot], User]:
    user = User(
        email=f"edit-{uuid4().hex}@example.com",
        display_name="Edit",
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
    shots: list[Shot] = []
    for number in (1, 2, 3):
        video = Artifact(
            project_id=project.id, artifact_type="video", storage_state="stored",
            object_key=f"obj/{uuid4().hex}", content_hash=f"{number}" * 64,
            mime_type="video/mp4", byte_size=2, duration_seconds=5 + number,
        )
        session.add(video)
        await session.flush()
        shot = Shot(
            project_id=project.id, scene_id=uuid4(), shot_number=number, version=1,
            visual_description=f"Shot {number}", formal_video_artifact_id=video.id,
        )
        session.add(shot)
        await session.flush()
        shots.append(shot)
    return project, shots, user


@pytest.mark.asyncio
async def test_phase9_gate_edit_flow_preserves_lineage(session: AsyncSession) -> None:
    project, shots, user = await _seed(session)
    built = await build_edit_session_from_shots(
        session,
        project_id=project.id,
        user_id=user.id,
        shot_ids=[shot.id for shot in shots],
    )
    session_id = UUID(built["session_id"])
    assert len(built["clips"]) == 3
    assert built["production_lineage"]["lineage_readonly"] is True

    # manual edit: reorder + trim via the adapter
    adapter = EditingAdapter(session)
    loaded = await adapter.load_timeline(project_id=project.id, session_id=session_id)
    clips = list(loaded.timeline.get("clips", []))
    # reorder: reverse
    clips.reverse()
    for clip in clips:
        clip["duration_seconds"] = 3.0  # trim
    edited = await adapter.save_timeline(
        project_id=project.id, session_id=session_id,
        timeline={"clips": clips, "metadata": {"edited": True}},
    )
    assert edited.status == "draft"

    # reopen
    reopened = await adapter.load_timeline(project_id=project.id, session_id=session_id)
    assert len(reopened.timeline["clips"]) == 3
    assert reopened.timeline["clips"][0]["duration_seconds"] == 3.0

    # export
    exported = await adapter.export(project_id=project.id, session_id=session_id)
    assert exported["clip_count"] == 3
    assert exported["duration_seconds"] == 9.0

    # production lineage unchanged: formal video artifacts still referenced
    for shot in shots:
        row = await session.get(Shot, shot.id)
        assert row.formal_video_artifact_id is not None
        artifact = await session.get(Artifact, row.formal_video_artifact_id)
        assert artifact is not None
