"""P1-03 formal-video hand-off tests for the read-only OpenCut manifest."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.access.projects import ProjectService
from app.api.v1.opencut import opencut_manifest
from app.assets.models import Episode, Scene, Shot
from app.execution.models import Artifact, GraphNode, NodeRun
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


async def _project(session: AsyncSession, *, suffix: str) -> tuple[User, Project]:
    user = User(
        email=f"opencut-{suffix}-{uuid4().hex}@example.com",
        display_name="OpenCut Owner",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"OpenCut {suffix}")
    session.add(workspace)
    await session.flush()
    project = await ProjectService(session).create_project(
        workspace_id=workspace.id,
        name=f"OpenCut {suffix}",
        aspect_ratio="16:9",
        actor=user,
    )
    return user, project


async def _shot(
    session: AsyncSession,
    *,
    project: Project,
    episode: Episode,
    scene_number: int,
    shot_number: int,
    sort_order: int,
) -> Shot:
    scene = Scene(
        episode_id=episode.id,
        scene_number=scene_number,
        location_name=f"Scene {scene_number}",
        time_of_day="day",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    shot = Shot(
        project_id=project.id,
        scene_id=scene.id,
        shot_number=shot_number,
        shot_type="medium",
        camera_move="static",
        visual_description="A shot",
        dialogue="",
        duration_seconds=Decimal("3"),
        status="complete",
        sort_order=sort_order,
    )
    session.add(shot)
    await session.flush()
    return shot


async def _video_artifact(
    session: AsyncSession,
    *,
    project: Project,
    created_by: UUID,
    shot: Shot,
    label: str,
    node_type: str = "video",
    artifact_type: str = "video",
    experiment_id: str | None = None,
) -> tuple[Artifact, NodeRun]:
    graph_version_id = uuid4()
    node = GraphNode(
        graph_version_id=graph_version_id,
        node_key=node_type,
        node_type=node_type,
        display_name=node_type.title(),
    )
    session.add(node)
    await session.flush()
    snapshot: dict[str, object] = {
        "shot_id": str(shot.id),
        "stage": "video" if node_type == "video" else "image_keyframe",
        "node_key": node_type,
    }
    if experiment_id is not None:
        snapshot["experiment_id"] = experiment_id
    run = NodeRun(
        project_id=project.id,
        graph_version_id=graph_version_id,
        graph_node_id=node.id,
        idempotency_key=f"{label}-{uuid4().hex}",
        input_hash=uuid4().hex * 2,
        input_snapshot=snapshot,
        status="completed",
        created_by=created_by,
    )
    session.add(run)
    await session.flush()
    artifact = Artifact(
        project_id=project.id,
        artifact_type=artifact_type,
        storage_state="available",
        object_key=f"opencut/{project.id}/{label}-{uuid4().hex}",
        content_hash=uuid4().hex * 2,
        mime_type="video/mp4" if artifact_type == "video" else "image/png",
        byte_size=1,
        duration_seconds=Decimal("3") if artifact_type == "video" else None,
        produced_by_run_id=run.id,
    )
    session.add(artifact)
    await session.flush()
    run.result_artifact_id = artifact.id
    await session.flush()
    return artifact, run


@pytest.mark.asyncio
async def test_manifest_uses_only_formal_video_pointer_and_canonical_order(
    session: AsyncSession,
) -> None:
    user, project = await _project(session, suffix="main")
    _other_user, other_project = await _project(session, suffix="other")

    episode_two = Episode(project_id=project.id, episode_number=2, title="E2", synopsis="")
    episode_one = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add_all([episode_two, episode_one])
    await session.flush()

    # Insert in a deliberately non-canonical order.  Episode -> Scene -> Shot
    # ordering must come from the hierarchy, not insertion order.
    shot_e2 = await _shot(
        session,
        project=project,
        episode=episode_two,
        scene_number=1,
        shot_number=1,
        sort_order=1,
    )
    shot_e1_s2 = await _shot(
        session,
        project=project,
        episode=episode_one,
        scene_number=2,
        shot_number=1,
        sort_order=1,
    )
    shot_e1_s1 = await _shot(
        session,
        project=project,
        episode=episode_one,
        scene_number=1,
        shot_number=1,
        sort_order=1,
    )

    formal, formal_run = await _video_artifact(
        session, project=project, created_by=user.id, shot=shot_e1_s2, label="formal"
    )
    shot_e1_s2.formal_video_artifact_id = formal.id

    # A newer successful video is still only a candidate without the Shot
    # pointer, and must not displace the selected formal artifact.
    candidate, _candidate_run = await _video_artifact(
        session, project=project, created_by=user.id, shot=shot_e1_s2, label="candidate"
    )
    latest_unformal, _latest_run = await _video_artifact(
        session, project=project, created_by=user.id, shot=shot_e1_s1, label="latest-unformal"
    )
    keyframe, _keyframe_run = await _video_artifact(
        session,
        project=project,
        created_by=user.id,
        shot=shot_e2,
        label="formal-keyframe",
        node_type="keyframe",
        artifact_type="image",
    )
    shot_e2.formal_keyframe_artifact_id = keyframe.id

    cross_project, _cross_run = await _video_artifact(
        session,
        project=other_project,
        created_by=_other_user.id,
        shot=shot_e2,
        label="cross-project",
    )
    shot_e2.formal_video_artifact_id = cross_project.id
    await session.flush()

    # The direct function call exercises the same DB-backed GET assembler used
    # by the API route, with the owner/project authorization seam intact.
    result = await opencut_manifest(project.id, user, session)
    video_track = next(track for track in result.tracks if track.kind == "video")

    assert [clip.shot_id for clip in video_track.clips] == [shot_e1_s2.id]
    assert [clip.artifact_id for clip in video_track.clips] == [formal.id]
    assert video_track.clips[0].trace.artifact_id == formal.id
    assert video_track.clips[0].trace.node_run_id == formal_run.id
    assert video_track.clips[0].source_url == (
        f"/api/v1/projects/{project.id}/artifacts/{formal.id}/content"
    )

    # No unformal candidate, latest output, keyframe, or cross-project object
    # may leak into the video timeline/shot formal artifact projection.
    serialized = str(result.model_dump())
    assert str(candidate.id) not in serialized
    assert str(latest_unformal.id) not in serialized
    assert str(keyframe.id) not in serialized
    assert str(cross_project.id) not in serialized
    assert [shot.shot_id for shot in result.shots] == [
        shot_e1_s1.id,
        shot_e1_s2.id,
        shot_e2.id,
    ]


@pytest.mark.asyncio
async def test_manifest_empty_formal_line_has_no_video_clips(session: AsyncSession) -> None:
    user, project = await _project(session, suffix="empty")
    episode = Episode(project_id=project.id, episode_number=1, title="E1", synopsis="")
    session.add(episode)
    await session.flush()
    shot = await _shot(
        session,
        project=project,
        episode=episode,
        scene_number=1,
        shot_number=1,
        sort_order=1,
    )
    shot.dialogue = "Not yet"
    await session.flush()

    result = await opencut_manifest(project.id, user, session)
    assert all(track.clips == [] for track in result.tracks)
    assert result.timeline.duration_seconds == "0"
    assert result.shots[0].shot_id == shot.id
    assert result.shots[0].artifact_ids == []
