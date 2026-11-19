"""An edit-session render freezes one version and binds MP4/SRT to its export (I9-02)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.delivery.export_service import ExportService
from app.delivery.models import Export
from app.delivery.render_execution import (
    create_edit_session_render,
    execute_edit_session_render,
)
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact, NodeRun
from app.production.service import GraphService
from app.shared.errors import ConflictError
from app.storage.minio_store import reset_object_store_for_tests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.test_editing_timeline_schema import _clip, _shot

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomclip-payload"


async def _exported_session(session: AsyncSession, *, clips: int = 1):
    project, user, shot, artifact = await _shot(session)
    assert artifact is not None
    store = reset_object_store_for_tests()
    stored = await store.put_bytes(object_key=f"obj/{uuid4().hex}", data=MP4, mime_type="video/mp4")
    artifact.object_key = stored.object_key
    artifact.content_hash = stored.content_hash
    artifact.byte_size = stored.byte_size
    artifact.mime_type = "video/mp4"
    await session.flush()
    adapter = EditingAdapter(session)
    row = await adapter.create_session(project_id=project.id, user_id=user.id, name="Edit")
    clips = [_clip(shot, artifact, order=index + 1) for index in range(clips)]
    # Subtitles come from the clip text; without any, no SRT is produced.
    clips[0]["subtitle"] = "第一句字幕"
    saved = await adapter.save_timeline(
        project_id=project.id,
        session_id=row.id,
        timeline={"schema_version": 2, "clips": clips, "metadata": {}},
        expected_session_version=1,
    )
    await session.commit()
    export, _created = await ExportService(session).create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        idempotency_key=f"export-{uuid4().hex}",
    )
    await session.commit()
    return project, user, shot, artifact, saved, export, store


@pytest.mark.asyncio
async def test_render_freezes_the_version_and_delivers_mp4_and_srt(
    session: AsyncSession,
) -> None:
    project, user, _shot_row, _artifact, saved, export, store = await _exported_session(session)
    run = await create_edit_session_render(
        session,
        project_id=project.id,
        session_id=saved.id,
        export_id=export.id,
        actor_id=user.id,
    )
    await session.commit()
    snapshot = run.input_snapshot
    assert snapshot["timeline_version"] == saved.version
    assert snapshot["timeline_hash"] == export.timeline_hash
    assert snapshot["export_id"] == str(export.id)
    assert len(snapshot["instructions"]) == 1

    materialized = await GraphService(session).materialize_definition(
        version_id=run.graph_version_id
    )
    node = materialized.nodes["edit_session_render"]
    result = await execute_edit_session_render(session, run=run, node=node, obj_store=store)
    await session.commit()

    rendered = await session.get(Artifact, result.artifact_id)
    assert rendered is not None
    assert rendered.mime_type == "video/mp4"
    assert rendered.produced_by_run_id == run.id
    assert (await store.get_bytes(object_key=rendered.object_key))[
        :12
    ] == b"\x00\x00\x00\x18ftypmp42"

    refreshed = await session.get(Export, export.id)
    assert refreshed is not None
    assert refreshed.result_artifact_id == rendered.id
    assert refreshed.status == "completed"
    assert refreshed.render_node_run_id == run.id
    subtitle_id = refreshed.manifest["subtitle_artifact_id"]
    assert subtitle_id is not None
    subtitle = await session.get(Artifact, UUID(str(subtitle_id)))
    assert subtitle is not None and subtitle.mime_type == "application/x-subrip"
    srt = (await store.get_bytes(object_key=subtitle.object_key)).decode("utf-8")
    assert "1\n00:00:00,000 --> 00:00:05,000" in srt


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_per_frozen_snapshot(session: AsyncSession) -> None:
    project, user, _shot_row, _artifact, saved, export, _store = await _exported_session(session)
    first = await create_edit_session_render(
        session, project_id=project.id, session_id=saved.id, export_id=export.id, actor_id=user.id
    )
    await session.commit()
    again = await create_edit_session_render(
        session, project_id=project.id, session_id=saved.id, export_id=export.id, actor_id=user.id
    )
    await session.commit()
    assert again.id == first.id
    runs = list(
        await session.scalars(select(NodeRun).where(NodeRun.graph_node_id == first.graph_node_id))
    )
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_a_stale_export_cannot_render_a_newer_session(session: AsyncSession) -> None:
    project, user, shot, artifact, saved, export, _store = await _exported_session(session)
    replacement = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="f" * 64,
        mime_type="video/mp4",
        byte_size=16,
    )
    session.add(replacement)
    await session.flush()
    shot.formal_video_artifact_id = replacement.id
    await session.flush()
    await EditingAdapter(session).save_timeline(
        project_id=project.id,
        session_id=saved.id,
        timeline={"schema_version": 2, "clips": [_clip(shot, replacement)], "metadata": {}},
        expected_session_version=2,
    )
    await session.commit()
    with pytest.raises(ConflictError) as stale:
        await create_edit_session_render(
            session,
            project_id=project.id,
            session_id=saved.id,
            export_id=export.id,
            actor_id=user.id,
        )
    assert stale.value.details["code"] == "RENDER_VERSION_STALE"
