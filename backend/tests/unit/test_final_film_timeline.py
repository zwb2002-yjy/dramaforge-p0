"""Final Film Timeline, queue boundary, retry, and Worker tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.delivery.models import Export, ExportItem
from app.editing.models import EditSession
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.final_film import (
    _load_timeline_refs,
    execute_final_film_node_run,
    queue_final_film_render,
)
from app.production.service import GraphService
from app.production.timeline_renderer import TimelineRenderClip, render_timeline
from app.runtime.scheduler import NodeRunScheduler
from app.shared.base import Base
from app.shared.enums import ProjectStage
from app.shared.errors import NotFoundError, ValidationAppError
from app.shared.security import hash_password
from app.storage.minio_store import get_object_store, reset_object_store_for_tests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    reset_object_store_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()
    reset_object_store_for_tests()


async def _seed_project(session: AsyncSession) -> tuple[Project, User]:
    user = User(
        email=f"final-{uuid4().hex}@example.com",
        display_name="Final Owner",
        password_hash=hash_password("x"),
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(owner_user_id=user.id, name=f"W-{uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Final Film Project",
        stage=ProjectStage.DRAFT.value,
        aspect_ratio="9:16",
        target_platform="general",
        style_bible={},
        budget_limit=Decimal("0"),
        budget_currency="USD",
        provider_dispatch_frozen=False,
    )
    session.add(project)
    await session.flush()
    return project, user


async def _seed_renderable_final_film(
    session: AsyncSession,
    *,
    shot_count: int = 1,
) -> tuple[Project, User, EditSession, list[Shot], list[Artifact]]:
    project, user = await _seed_project(session)
    episode = Episode(project_id=project.id, episode_number=1, title="Episode 1", synopsis="")
    session.add(episode)
    await session.flush()
    scene = Scene(
        episode_id=episode.id,
        scene_number=1,
        location_name="Rooftop",
        time_of_day="night",
        synopsis="",
    )
    session.add(scene)
    await session.flush()
    store = get_object_store()
    shots: list[Shot] = []
    formal_videos: list[Artifact] = []
    timeline_clips: list[dict[str, object]] = []
    for index in range(shot_count):
        shot = Shot(
            project_id=project.id,
            scene_id=scene.id,
            shot_number=index + 1,
            sort_order=index + 1,
            visual_description=f"Shot {index + 1}",
            dialogue=f"Line {index + 1}",
            duration_seconds=Decimal("5"),
        )
        session.add(shot)
        await session.flush()
        graph = await GraphService(session).create_graph(
            project_id=project.id,
            scope_type="shot",
            scope_entity_id=shot.id,
            template_key="shot-p0-v1",
            created_by=user.id,
            definition={
                "nodes": [
                    {"key": "video", "type": "video"},
                    {"key": "composite", "type": "composite"},
                ],
                "edges": [],
            },
        )
        assert graph.current_version_id is not None
        await GraphService(session).materialize_definition(version_id=graph.current_version_id)
        nodes = list(
            (
                await session.execute(
                    select(GraphNode).where(GraphNode.graph_version_id == graph.current_version_id)
                )
            )
            .scalars()
            .all()
        )
        composite_node = next(node for node in nodes if node.node_key == "composite")

        video_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/video-{index}.mp4",
            data=f"\x00\x00\x00\x18ftypmp42video-{index}".encode(),
            mime_type="video/mp4",
        )
        video_artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="available",
            object_key=video_stored.object_key,
            content_hash=video_stored.content_hash,
            mime_type="video/mp4",
            byte_size=video_stored.byte_size,
            duration_seconds=Decimal("5"),
        )
        session.add(video_artifact)
        await session.flush()
        voice_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/voice-{index}.wav",
            data=f"RIFFvoice-{index}".encode(),
            mime_type="audio/wav",
        )
        voice_artifact = Artifact(
            project_id=project.id,
            artifact_type="audio",
            storage_state="available",
            object_key=voice_stored.object_key,
            content_hash=voice_stored.content_hash,
            mime_type="audio/wav",
            byte_size=voice_stored.byte_size,
        )
        session.add(voice_artifact)
        subtitle_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/subtitle-{index}.srt",
            data=f"1\n00:00:00,000 --> 00:00:02,000\nLine {index + 1}\n".encode(),
            mime_type="application/x-subrip",
        )
        subtitle_artifact = Artifact(
            project_id=project.id,
            artifact_type="subtitle",
            storage_state="available",
            object_key=subtitle_stored.object_key,
            content_hash=subtitle_stored.content_hash,
            mime_type="application/x-subrip",
            byte_size=subtitle_stored.byte_size,
        )
        session.add(subtitle_artifact)
        await session.flush()
        composite_run = NodeRun(
            project_id=project.id,
            graph_version_id=graph.current_version_id,
            graph_node_id=composite_node.id,
            attempt_no=1,
            idempotency_key=f"formal-composite-{index}-{uuid4()}",
            input_hash="c" * 64,
            status="completed",
            input_snapshot={
                "shot_id": str(shot.id),
                "node_key": "composite",
                "execution_branch": "formal",
                "media_inputs": {
                    "video": {
                        "artifact_id": str(video_artifact.id),
                        "content_hash": video_artifact.content_hash,
                    },
                    "voice": {
                        "artifact_id": str(voice_artifact.id),
                        "content_hash": voice_artifact.content_hash,
                    },
                    "subtitle": {
                        "artifact_id": str(subtitle_artifact.id),
                        "content_hash": subtitle_artifact.content_hash,
                    },
                },
            },
            created_by=user.id,
        )
        session.add(composite_run)
        await session.flush()
        composite_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/composite-{index}.mp4",
            data=f"\x00\x00\x00\x18ftypmp42composite-{index}".encode(),
            mime_type="video/mp4",
        )
        composite_artifact = Artifact(
            project_id=project.id,
            artifact_type="video",
            storage_state="available",
            object_key=composite_stored.object_key,
            content_hash=composite_stored.content_hash,
            mime_type="video/mp4",
            byte_size=composite_stored.byte_size,
            duration_seconds=Decimal("5"),
            produced_by_run_id=composite_run.id,
        )
        session.add(composite_artifact)
        await session.flush()
        composite_run.result_artifact_id = composite_artifact.id
        shot.formal_video_artifact_id = video_artifact.id
        shot.formal_composite_artifact_id = composite_artifact.id
        formal_videos.append(video_artifact)
        shots.append(shot)
        timeline_clips.append(
            {
                "id": f"clip-{index + 1}",
                "shot_id": str(shot.id),
                "artifact_id": str(video_artifact.id),
                "order": index + 1,
                "duration_seconds": 5,
                "source_in_seconds": 0,
                "subtitle": "",
                "audio_id": None,
                "transition": None,
            }
        )
    edit = EditSession(
        project_id=project.id,
        name="Final timeline",
        status="draft",
        version=1,
        timeline={"clips": timeline_clips, "metadata": {}},
        production_lineage={"lineage_readonly": True},
        created_by=user.id,
    )
    session.add(edit)
    await session.commit()
    return project, user, edit, shots, formal_videos


async def _fake_enqueue(self: NodeRunScheduler, node_run_id: object) -> str:
    _ = self
    return f"job-{node_run_id}"


@pytest.mark.asyncio
async def test_load_timeline_refs_requires_persisted_version(session: AsyncSession) -> None:
    project, user = await _seed_project(session)
    edit = EditSession(
        project_id=project.id,
        name="Timeline v2",
        status="draft",
        version=2,
        timeline={"clips": [], "metadata": {}},
        production_lineage={"lineage_readonly": True},
        created_by=user.id,
    )
    session.add(edit)
    await session.commit()
    with pytest.raises(ValidationAppError) as exc:
        await _load_timeline_refs(
            session,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=3,
        )
    assert exc.value.details.get("code") == "TIMELINE_VERSION_MISMATCH"


@pytest.mark.asyncio
async def test_queue_rejects_empty_timeline(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user = await _seed_project(session)
    edit = EditSession(
        project_id=project.id,
        name="Empty timeline",
        status="draft",
        version=1,
        timeline={"clips": [], "metadata": {}},
        production_lineage={"lineage_readonly": True},
        created_by=user.id,
    )
    session.add(edit)
    await session.commit()
    with pytest.raises(ValidationAppError) as exc:
        await queue_final_film_render(
            session,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=1,
            actor_id=user.id,
            idempotency_key=None,
            name="Final",
        )
    assert exc.value.details.get("code") == "EMPTY_TIMELINE"


@pytest.mark.asyncio
async def test_queue_freezes_timeline_and_does_not_execute_provider(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, _shots, _videos = await _seed_renderable_final_film(session)
    edit.timeline["clips"][0].update(
        {
            "source_in_seconds": 1,
            "duration_seconds": 2,
            "subtitle": "Edited subtitle",
            "transition": {"kind": "crossfade", "duration_seconds": 0.2},
        }
    )
    edit.version = 2
    await session.commit()
    result = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=2,
        actor_id=user.id,
        idempotency_key="timeline-request-1",
        name="Final",
    )
    assert result.status == "queued"
    run = await session.get(NodeRun, result.node_run_id)
    assert run is not None and run.status == "queued" and run.attempt_no == 1
    assert (await session.execute(select(ProviderOperation))).scalars().all() == []
    clip = run.input_snapshot["timeline"]["clips"][0]
    assert clip["source_in_seconds"] == 1.0
    assert clip["duration_seconds"] == 2.0
    assert clip["subtitle"] == "Edited subtitle"
    assert clip["transition"]["kind"] == "crossfade"


@pytest.mark.asyncio
async def test_failed_final_film_retry_uses_next_attempt_and_same_external_key(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, _shots, _videos = await _seed_renderable_final_film(session)
    first = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="retryable-final",
        name="Final",
    )
    first_run = await session.get(NodeRun, first.node_run_id)
    assert first_run is not None
    first_run.status = "failed"
    first_run.error_code = "FINAL_FILM_RENDER_FAILED"
    await session.commit()
    second = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="retryable-final",
        name="Final",
    )
    second_run = await session.get(NodeRun, second.node_run_id)
    assert second_run is not None
    assert second_run.id != first_run.id
    assert second_run.attempt_no == 2
    assert second_run.parent_run_id == first_run.id
    assert second_run.status == "queued"


@pytest.mark.asyncio
async def test_queued_retry_is_idempotent_and_key_reuse_is_rejected(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, _shots, _videos = await _seed_renderable_final_film(session)
    first = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="completed-final",
        name="Final",
    )
    same = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="completed-final",
        name="Final",
    )
    assert same.node_run_id == first.node_run_id
    run = await session.get(NodeRun, first.node_run_id)
    assert run is not None
    run.status = "failed"
    await session.commit()
    retry = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="completed-final",
        name="Final",
    )
    assert retry.node_run_id != run.id
    assert retry.attempt_no == 2
    edit.timeline["metadata"] = {"changed": True}
    edit.version = 2
    await session.commit()
    with pytest.raises(ValidationAppError) as exc:
        await queue_final_film_render(
            session,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=2,
            actor_id=user.id,
            idempotency_key="completed-final",
            name="Final",
        )
    assert exc.value.details["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_worker_renders_frozen_timeline_and_persists_lineage(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(NodeRunScheduler, "enqueue_node_run_only", _fake_enqueue)
    project, user, edit, shots, _videos = await _seed_renderable_final_film(session, shot_count=2)
    queued = await queue_final_film_render(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="worker-final",
        name="Final",
    )
    run = await session.get(NodeRun, queued.node_run_id)
    assert run is not None
    run.status = "running"
    await session.commit()
    node = await session.get(GraphNode, run.graph_node_id)
    assert node is not None
    result = await execute_final_film_node_run(
        session,
        run=run,
        node=node,
        obj_store=get_object_store(),
    )
    assert result.artifact_id is not None
    assert run.status == "completed"
    assert run.attempt_no == 1
    artifact = await session.get(Artifact, result.artifact_id)
    assert artifact is not None and artifact.produced_by_run_id == run.id
    export = (
        await session.execute(select(Export).where(Export.project_id == project.id))
    ).scalars().one()
    assert export.result_artifact_id == artifact.id
    items = (
        await session.execute(select(ExportItem).where(ExportItem.export_id == export.id))
    ).scalars().all()
    assert len(items) == len(shots)
    assert all(item.metadata_json["timeline_edit"] for item in items)
    operation = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == run.id)
        )
    ).scalars().one()
    assert operation.status == "succeeded"
    assert operation.execution_path_version == "local-final-film-worker-v2"


@pytest.mark.asyncio
async def test_timeline_renderer_reports_edit_semantics_in_test_mode() -> None:
    result = await render_timeline(
        [
            TimelineRenderClip(
                clip_id="clip-1",
                video_artifact_id="video-1",
                video_bytes=b"video",
                audio_bytes=b"audio",
                subtitle_text="Edited subtitle",
                source_in_seconds=1.25,
                duration_seconds=2.5,
                transition_kind=None,
            )
        ],
        lineage="lineage",
    )
    assert result.summary["timeline_renderer"] == "ffmpeg-v2"
    assert result.summary["clip_count"] == 1
    assert result.ffprobe["format"]["duration"] == "2.500"


@pytest.mark.asyncio
async def test_missing_edit_session_is_not_found(session: AsyncSession) -> None:
    project, user = await _seed_project(session)
    with pytest.raises(NotFoundError):
        await queue_final_film_render(
            session,
            project_id=project.id,
            edit_session_id=uuid4(),
            expected_timeline_version=1,
            actor_id=user.id,
            idempotency_key=None,
            name="Final",
        )
