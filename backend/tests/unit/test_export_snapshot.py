"""An export freezes one timeline version and never re-binds a later edit (I9-02)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.delivery.export_service import ExportService, timeline_hash
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact
from app.shared.errors import ValidationAppError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.test_editing_timeline_schema import _clip, _shot


async def _saved_session(session: AsyncSession):
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
    await session.commit()
    return project, user, shot, artifact, saved


@pytest.mark.asyncio
async def test_export_freezes_the_timeline_version_and_clip_artifacts(
    session: AsyncSession,
) -> None:
    project, user, _shot_row, artifact, saved = await _saved_session(session)
    service = ExportService(session)
    export, created = await service.create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        idempotency_key=f"export-{uuid4().hex}",
    )
    await session.commit()
    assert created is True
    assert export.edit_session_id == saved.id
    assert export.timeline_version == saved.version == 2
    assert export.timeline_hash == timeline_hash(dict(saved.timeline))
    assert export.manifest["clip_count"] == 1
    assert export.episode_id == saved.episode_id

    items = await service.items_of(export_id=export.id)
    assert len(items) == 1
    assert items[0].ordinal == 1
    assert items[0].source_artifact_id == artifact.id
    assert items[0].metadata_json["timeline_version"] == 2


@pytest.mark.asyncio
async def test_repeated_key_returns_the_original_export_after_an_edit(
    session: AsyncSession,
) -> None:
    """Receipt priority: a later edit never rewrites an existing export."""
    project, user, _shot_row, artifact, saved = await _saved_session(session)
    key = f"export-{uuid4().hex}"
    service = ExportService(session)
    first, created = await service.create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        idempotency_key=key,
    )
    await session.commit()
    assert created is True

    # A new artifact releases and the session is saved again (version 3).
    replacement = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=f"obj/{uuid4().hex}",
        content_hash="e" * 64,
        mime_type="video/mp4",
        byte_size=2048,
    )
    session.add(replacement)
    await session.flush()
    shot = await session.get(type(_shot_row), _shot_row.id)
    assert shot is not None
    shot.formal_video_artifact_id = replacement.id
    await session.flush()
    await EditingAdapter(session).save_timeline(
        project_id=project.id,
        session_id=saved.id,
        timeline={
            "schema_version": 2,
            "clips": [_clip(shot, replacement)],
            "metadata": {},
        },
        expected_session_version=2,
    )
    await session.commit()

    replay, created_again = await service.create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        idempotency_key=key,
    )
    assert created_again is False
    assert replay.id == first.id
    assert replay.timeline_version == 2
    items = await service.items_of(export_id=first.id)
    assert [item.source_artifact_id for item in items] == [artifact.id]

    # A different key records the newer version instead of touching the first.
    newer, created_new = await service.create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        idempotency_key=f"export-{uuid4().hex}",
    )
    assert created_new is True
    assert newer.timeline_version == 3
    assert newer.timeline_hash != first.timeline_hash


@pytest.mark.asyncio
async def test_export_route_returns_201_then_200_for_the_same_receipt(
    session: AsyncSession,
) -> None:
    from app.api.v1.editing import EditSessionExportRequest, create_edit_session_export
    from fastapi import Response

    project, user, _shot_row, artifact, saved = await _saved_session(session)
    body = EditSessionExportRequest(idempotency_key=f"export-{uuid4().hex}")
    created = Response()
    first = await create_edit_session_export(
        project_id=project.id,
        session_id=saved.id,
        body=body,
        user=user,
        session=session,
        response=created,
        _=None,
    )
    assert created.status_code == 201
    assert first.timeline_version == 2
    assert first.manifest["clip_count"] == 1

    replay = Response()
    second = await create_edit_session_export(
        project_id=project.id,
        session_id=saved.id,
        body=body,
        user=user,
        session=session,
        response=replay,
        _=None,
    )
    assert replay.status_code == 200
    assert second.id == first.id
    assert second.timeline_hash == first.timeline_hash


@pytest.mark.asyncio
async def test_render_formats_and_unbound_clips_are_refused(session: AsyncSession) -> None:
    project, user, _shot_row, _artifact, saved = await _saved_session(session)
    service = ExportService(session)

    with pytest.raises(ValidationAppError) as render:
        await service.create_session_export(
            project_id=project.id,
            session_id=saved.id,
            requested_by=user.id,
            format="mp4",
        )
    assert render.value.details["code"] == "EXPORT_RENDER_REQUIRED"

    with pytest.raises(ValidationAppError) as unsupported:
        await service.create_session_export(
            project_id=project.id,
            session_id=saved.id,
            requested_by=user.id,
            format="pdf",
        )
    assert unsupported.value.details["code"] == "EXPORT_FORMAT_UNSUPPORTED"

    # A schema 2 clip without a bound artifact cannot be exported silently.
    unbound = await EditingAdapter(session).load_timeline(
        project_id=project.id, session_id=saved.id
    )
    timeline = dict(unbound.timeline)
    timeline["clips"] = [{**timeline["clips"][0], "selection_snapshot": None}]
    unbound.timeline = timeline
    await session.flush()
    with pytest.raises(ValidationAppError) as refused:
        await service.create_session_export(
            project_id=project.id,
            session_id=saved.id,
            requested_by=user.id,
        )
    assert refused.value.details["code"] == "EXPORT_CLIP_UNBOUND"
