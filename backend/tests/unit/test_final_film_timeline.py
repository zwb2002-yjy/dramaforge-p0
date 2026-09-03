"""Final Film Timeline scoping and fail-closed unit tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import Episode, Scene, Shot
from app.config import clear_settings_cache
from app.delivery.models import Export, ExportItem
from app.editing.models import EditSession
from app.execution.models import Artifact, GraphNode, NodeRun, ProviderOperation
from app.production.final_film import (
    _load_timeline_refs,
    render_final_film,
)
from app.production.service import GraphService
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
    store = reset_object_store_for_tests()
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
        assert any(node.node_key == "video" for node in nodes)
        composite_node = next(node for node in nodes if node.node_key == "composite")
        video_data = f"video-{index}".encode()
        video_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/video-{index}.mp4",
            data=video_data,
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
        voice_data = f"voice-{index}".encode()
        voice_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/voice-{index}.wav",
            data=voice_data,
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
        subtitle_data = f"1\n00:00:00,000 --> 00:00:02,000\nLine {index + 1}\n".encode()
        subtitle_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/subtitle-{index}.srt",
            data=subtitle_data,
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
            input_hash=("c" * 64),
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
        composite_data = f"\x00\x00\x00\x18ftypmp42composite-{index}".encode()
        composite_stored = await store.put_bytes(
            object_key=f"projects/{project.id}/test/composite-{index}.mp4",
            data=composite_data,
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


@pytest.mark.asyncio
async def test_load_timeline_refs_requires_persisted_version(session: AsyncSession) -> None:
    project, _user = await _seed_project(session)
    session.add(
        EditSession(
            project_id=project.id,
            name="Timeline v2",
            status="draft",
            version=2,
            timeline={"clips": [], "metadata": {}},
            production_lineage={"lineage_readonly": True},
            created_by=_user.id,
        )
    )
    await session.commit()
    edit_id = (
        await session.execute(
            select(EditSession.id).where(EditSession.project_id == project.id)
        )
    ).scalar_one()
    with pytest.raises(ValidationAppError) as exc:
        await _load_timeline_refs(
            session,
            project_id=project.id,
            edit_session_id=edit_id,
            expected_timeline_version=3,
        )
    assert exc.value.details.get("code") == "TIMELINE_VERSION_MISMATCH"


@pytest.mark.asyncio
async def test_render_empty_timeline_fails_closed(session: AsyncSession) -> None:
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
        await render_final_film(
            session,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=1,
            actor_id=user.id,
        )
    assert exc.value.details.get("code") == "EMPTY_TIMELINE"


@pytest.mark.asyncio
async def test_missing_edit_session_is_not_found(session: AsyncSession) -> None:
    project, user = await _seed_project(session)
    with pytest.raises(NotFoundError):
        await render_final_film(
            session,
            project_id=project.id,
            edit_session_id=uuid4(),
            expected_timeline_version=None,
            actor_id=user.id,
        )


@pytest.mark.asyncio
async def test_render_uses_timeline_formal_branch_and_persists_complete_lineage(
    session: AsyncSession,
) -> None:
    project, user, edit, shots, _formal_videos = await _seed_renderable_final_film(
        session, shot_count=2
    )
    # A newer experiment attempt for the same Shot must never replace the
    # current Formal composite selected by the timeline.
    composite_artifact = await session.get(Artifact, shots[0].formal_composite_artifact_id)
    assert composite_artifact is not None and composite_artifact.produced_by_run_id is not None
    formal_composite_run = await session.get(NodeRun, composite_artifact.produced_by_run_id)
    assert formal_composite_run is not None
    experiment_run = NodeRun(
        project_id=project.id,
        graph_version_id=formal_composite_run.graph_version_id,
        graph_node_id=formal_composite_run.graph_node_id,
        attempt_no=99,
        idempotency_key=f"experiment-composite-{uuid4()}",
        input_hash="e" * 64,
        status="completed",
        input_snapshot={
            **dict(formal_composite_run.input_snapshot),
            "execution_branch": "experiment",
            "experiment_id": str(uuid4()),
        },
        created_by=user.id,
    )
    session.add(experiment_run)
    await session.flush()
    experiment_artifact = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"projects/{project.id}/test/experiment.mp4",
        content_hash="d" * 64,
        mime_type="video/mp4",
        byte_size=32,
        duration_seconds=Decimal("5"),
        produced_by_run_id=experiment_run.id,
    )
    session.add(experiment_artifact)
    # A still-newer non-current Formal attempt must also lose to the Shot's
    # current Formal composite pointer.  Attempt number alone is not authority.
    stale_formal_run = NodeRun(
        project_id=project.id,
        graph_version_id=formal_composite_run.graph_version_id,
        graph_node_id=formal_composite_run.graph_node_id,
        attempt_no=100,
        idempotency_key=f"stale-formal-composite-{uuid4()}",
        input_hash="f" * 64,
        status="completed",
        input_snapshot=dict(formal_composite_run.input_snapshot),
        created_by=user.id,
    )
    session.add(stale_formal_run)
    await session.flush()
    stale_formal_artifact = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"projects/{project.id}/test/stale-formal.mp4",
        content_hash="a" * 64,
        mime_type="video/mp4",
        byte_size=32,
        duration_seconds=Decimal("5"),
        produced_by_run_id=stale_formal_run.id,
    )
    session.add(stale_formal_artifact)
    await session.flush()
    stale_formal_run.result_artifact_id = stale_formal_artifact.id
    await session.commit()

    result = await render_final_film(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="final-film-lineage-test",
    )
    assert result.timeline_clip_count == 2
    assert result.shot_count == 2
    assert result.mime_type == "video/mp4"
    assert result.byte_size > 0
    assert result.storage_state == "available"
    assert len(result.content_hash) == 64
    assert all(result.ffprobe["assertions"].values()) if result.ffprobe else False
    assert [item["formal_video_artifact_id"] for item in result.formal_references] == [
        str(shot.formal_video_artifact_id) for shot in shots
    ]
    assert result.composite_artifact_ids == [
        str(shot.formal_composite_artifact_id) for shot in shots
    ]
    final_artifact = await session.get(Artifact, result.artifact_id)
    assert final_artifact is not None
    assert final_artifact.produced_by_run_id == result.node_run_id
    export_items = (
        await session.execute(
            select(ExportItem)
            .where(ExportItem.export_id == result.export_id)
            .order_by(ExportItem.ordinal)
        )
    ).scalars().all()
    assert len(export_items) == 2
    assert all(item.metadata_json["media_inputs"]["voice"] for item in export_items)
    assert all(item.metadata_json["media_inputs"]["subtitle"] for item in export_items)
    operation = await session.get(ProviderOperation, result.provider_operation_id)
    assert operation is not None
    assert operation.node_run_id == result.node_run_id
    assert operation.actual_provider == "local_ffmpeg"
    assert operation.status == "succeeded"


@pytest.mark.asyncio
async def test_render_idempotency_returns_one_export_and_one_artifact(
    session: AsyncSession,
) -> None:
    project, user, edit, _shots, _formal_videos = await _seed_renderable_final_film(session)
    first = await render_final_film(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="same-final-film-request",
    )
    second = await render_final_film(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="same-final-film-request",
    )
    assert second.export_id == first.export_id
    assert second.artifact_id == first.artifact_id
    assert second.node_run_id == first.node_run_id
    exports = (
        await session.execute(
            select(Export).where(
                Export.project_id == project.id,
                Export.format == "dramaforge-final-film-v1",
            )
        )
    ).scalars().all()
    assert len(exports) == 1


@pytest.mark.asyncio
async def test_render_rejects_reused_idempotency_key_for_different_timeline(
    session: AsyncSession,
) -> None:
    project, user, edit, _shots, _formal_videos = await _seed_renderable_final_film(session)
    await render_final_film(
        session,
        project_id=project.id,
        edit_session_id=edit.id,
        expected_timeline_version=1,
        actor_id=user.id,
        idempotency_key="reused-final-film-key",
    )
    edit.timeline["metadata"] = {"changed": True}
    edit.version = 2
    await session.commit()
    with pytest.raises(ValidationAppError) as exc:
        await render_final_film(
            session,
            project_id=project.id,
            edit_session_id=edit.id,
            expected_timeline_version=2,
            actor_id=user.id,
            idempotency_key="reused-final-film-key",
        )
    assert exc.value.details["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_ffmpeg_failure_persists_failed_run_and_cleans_final_object(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, user, edit, _shots, _formal_videos = await _seed_renderable_final_film(session)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DRAMA_FORCE_MEMORY_STORE", "1")
    monkeypatch.setenv("SESSION_SECRET", "test-production-session-secret-32-characters")
    monkeypatch.setenv("WORKER_TOKEN", "test-production-worker-token-32-characters")
    monkeypatch.setenv(
        "BYOK_FERNET_KEY", "v0v3D-eSZ4JB_qjFNWVlfYUUKulGroB1bVVa8Seifqc="
    )
    clear_settings_cache()

    async def failing_ffmpeg(**_kwargs: object) -> dict[str, object]:
        raise ValidationAppError(
            "controlled ffmpeg failure",
            details={"code": "FINAL_FILM_RENDER_FAILED"},
        )

    monkeypatch.setattr("app.production.final_film._render_with_ffmpeg", failing_ffmpeg)
    try:
        with pytest.raises(ValidationAppError, match="controlled ffmpeg failure"):
            await render_final_film(
                session,
                project_id=project.id,
                edit_session_id=edit.id,
                expected_timeline_version=1,
                actor_id=user.id,
                idempotency_key="ffmpeg-failure",
            )
    finally:
        clear_settings_cache()

    failed_run = (
        await session.execute(
            select(NodeRun).where(NodeRun.idempotency_key.like("final-film:%"))
        )
    ).scalars().one()
    assert failed_run.status == "failed"
    assert failed_run.error_code == "FINAL_FILM_RENDER_FAILED"
    failed_operation = (
        await session.execute(
            select(ProviderOperation).where(ProviderOperation.node_run_id == failed_run.id)
        )
    ).scalars().one()
    assert failed_operation.status == "failed"
    store = get_object_store()
    with pytest.raises(KeyError):
        await store.get_bytes(
            object_key=f"projects/{project.id}/final-film/{failed_run.id}.mp4"
        )
