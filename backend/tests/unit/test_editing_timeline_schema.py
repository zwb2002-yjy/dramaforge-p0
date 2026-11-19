"""Edit timeline schema 2 is typed and its sources are verified at Save (I9-01)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact
from app.production.models import ShotReferenceBinding  # noqa: F401 - document intent
from app.shared.errors import ConflictError, ValidationAppError
from sqlalchemy.ext.asyncio import AsyncSession


async def _shot(
    session: AsyncSession, *, formal: bool = True
) -> tuple[Project, User, Shot, Artifact | None]:
    suffix = uuid4().hex[:8]
    user = User(email=f"edit-{suffix}@example.com", display_name="E", password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{suffix}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name=f"P-{suffix}",
        aspect_ratio="9:16",
        budget_limit=0,
        work_type="single_comic",
        planned_episode_count=1,
    )
    session.add(project)
    await session.flush()
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
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
        sort_order=1,
        status="draft",
        visual_description="frame",
        duration_seconds=5,
    )
    session.add(shot)
    await session.flush()
    artifact = None
    if formal:
        artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="available",
            object_key=f"obj/{uuid4().hex}",
            content_hash="a" * 64,
            mime_type="video/mp4",
            byte_size=1024,
            duration_seconds=5,
        )
        session.add(artifact)
        await session.flush()
        shot.formal_video_artifact_id = artifact.id
        await session.flush()
    return project, user, shot, artifact


def _clip(shot: Shot, artifact: Artifact, *, order: int = 1, kind: str = "shot_formal"):
    return {
        "id": f"clip-{order}",
        "order": order,
        "duration_seconds": 5.0,
        "subtitle": "",
        "transition": None,
        "source": {
            "kind": kind,
            "shot_id": str(shot.id),
            "artifact_id": str(artifact.id),
        },
    }


@pytest.mark.asyncio
async def test_schema1_timeline_is_stored_without_an_upgrade(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    legacy = {
        "clips": [
            {
                "id": "clip-1",
                "shot_id": str(shot.id),
                "artifact_id": str(artifact.id),
                "order": 1,
                "duration_seconds": 5.0,
                "subtitle": "",
                "audio_id": None,
                "transition": None,
            }
        ],
        "metadata": {"note": "legacy"},
    }
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={**legacy, "schema_version": 1},
        expected_session_version=1,
    )
    # No on-disk schema marker is invented for a schema 1 document.
    assert "schema_version" not in saved.timeline
    assert saved.timeline["clips"] == legacy["clips"]
    assert saved.version == 2


@pytest.mark.asyncio
async def test_schema2_shot_formal_source_is_verified_and_stored(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
        expected_session_version=1,
    )
    assert saved.timeline["schema_version"] == 2
    clip = saved.timeline["clips"][0]
    assert clip["source"]["kind"] == "shot_formal"
    assert clip["source"]["artifact_id"] == str(artifact.id)


@pytest.mark.asyncio
async def test_schema2_rejects_a_source_that_is_not_the_current_formal_video(
    session: AsyncSession,
) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    other = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="b" * 64,
        mime_type="video/mp4",
        byte_size=1024,
    )
    session.add(other)
    await session.flush()
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    stale = _clip(shot, artifact)
    stale["source"]["artifact_id"] = str(other.id)
    with pytest.raises(ValidationAppError) as rejected:
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [stale], "metadata": {}},
            expected_session_version=1,
        )
    assert rejected.value.details["code"] == "EDIT_SOURCE_NOT_FORMAL"
    await session.rollback()


@pytest.mark.asyncio
async def test_schema2_refuses_unverifiable_source_kinds(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    adopted = _clip(shot, artifact)
    adopted["source"] = {
        "kind": "asset_version",
        "asset_id": str(uuid4()),
        "asset_version_id": str(uuid4()),
    }
    with pytest.raises(ValidationAppError) as refused:
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [adopted], "metadata": {}},
            expected_session_version=1,
        )
    assert refused.value.details["code"] == "EDIT_SOURCE_UNVERIFIED"
    assert refused.value.details["kind"] == "asset_version"
    await session.rollback()


@pytest.mark.asyncio
async def test_schema2_rejects_malformed_documents(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    # Build the documents before committing: the commit expires ORM attributes.
    missing_source = _clip(shot, artifact)
    missing_source.pop("source")
    duplicate = [_clip(shot, artifact, order=1), _clip(shot, artifact, order=2)]
    duplicate[1]["id"] = duplicate[0]["id"]
    gap = [_clip(shot, artifact, order=1), _clip(shot, artifact, order=3)]
    unknown_kind = _clip(shot, artifact, kind="private_upload")

    # Each rejected save rolls back, so the session row must already be durable.
    # Capture raw ids first: committing expires the ORM instances.
    project_id, session_id = project.id, row.id
    await session.commit()

    for document in (missing_source, duplicate, gap, unknown_kind):
        clips = document if isinstance(document, list) else [document]
        with pytest.raises(ValidationAppError) as rejected:
            await adapter.save_timeline(
                project_id=project_id,
                session_id=session_id,
                timeline={"schema_version": 2, "clips": clips, "metadata": {}},
                expected_session_version=1,
            )
        assert rejected.value.details["code"] == "EDIT_TIMELINE_INVALID"
        await session.rollback()


@pytest.mark.asyncio
async def test_save_keeps_the_version_conflict_contract(session: AsyncSession) -> None:
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    with pytest.raises(ConflictError):
        await adapter.save_timeline(
            project_id=project.id,
            session_id=row.id,
            timeline={"schema_version": 2, "clips": [_clip(shot, artifact)], "metadata": {}},
            expected_session_version=7,
        )
