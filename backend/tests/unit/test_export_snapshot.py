"""An export freezes one timeline version and never re-binds a later edit (I9-02)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.editing.adapter import EditingAdapter
from app.execution.models import Artifact
from app.production.session_exports import SessionExports, timeline_hash
from app.shared.errors import ValidationAppError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from tests.unit.test_editing_timeline_schema import _clip, _shot


def _request(range_header: str | None = None) -> Request:
    headers = [(b"range", range_header.encode())] if range_header else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


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
    service = SessionExports(session)
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
    service = SessionExports(session)
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
async def test_delivery_download_serves_only_rendered_exports(session: AsyncSession) -> None:
    from app.api.v1.editing import download_export_content
    from app.delivery.models import Export
    from app.storage.minio_store import reset_object_store_for_tests

    store = reset_object_store_for_tests()
    project, user, _shot_row, _artifact, saved = await _saved_session(session)
    service = SessionExports(session)
    export, _created = await service.create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        idempotency_key=f"export-{uuid4().hex}",
    )
    await session.commit()

    # A queued receipt is not a film: no result artifact means no delivery.
    with pytest.raises(ValidationAppError) as pending:
        await download_export_content(
            project_id=project.id,
            export_id=export.id,
            request=_request(),
            user=user,
            session=session,
        )
    assert pending.value.details["code"] == "EXPORT_NOT_DELIVERABLE"

    stored = await store.put_bytes(
        object_key=f"obj/{uuid4().hex}",
        data=b"\x00\x00\x00\x18ftypmp42rendered-film",
        mime_type="video/mp4",
    )
    rendered = Artifact(
        project_id=project.id,
        artifact_type="video",
        storage_state="available",
        object_key=stored.object_key,
        content_hash=stored.content_hash,
        mime_type="video/mp4",
        byte_size=stored.byte_size,
    )
    session.add(rendered)
    await session.flush()
    row = await session.get(Export, export.id)
    assert row is not None
    row.result_artifact_id = rendered.id
    row.status = "completed"
    await session.commit()

    response = await download_export_content(
        project_id=project.id,
        export_id=export.id,
        request=_request(),
        user=user,
        session=session,
    )
    assert response.media_type == "video/mp4"
    assert response.body == b"\x00\x00\x00\x18ftypmp42rendered-film"
    assert response.headers["content-length"] == str(len(response.body))
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]

    # A single range is served as 206 with an exact Content-Range.
    partial = await download_export_content(
        project_id=project.id,
        export_id=export.id,
        request=_request("bytes=0-3"),
        user=user,
        session=session,
    )
    assert partial.status_code == 206
    assert partial.body == response.body[:4]
    assert partial.headers["content-range"] == f"bytes 0-3/{len(response.body)}"

    # An unsatisfiable range is 416, never a silent full body.
    unsatisfiable = await download_export_content(
        project_id=project.id,
        export_id=export.id,
        request=_request("bytes=999999-"),
        user=user,
        session=session,
    )
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["content-range"] == f"bytes */{len(response.body)}"


@pytest.mark.asyncio
async def test_delivery_download_rejects_another_projects_export(
    session: AsyncSession,
) -> None:
    from app.api.v1.editing import download_export_content
    from app.shared.errors import ForbiddenError

    project, user, _shot_row, _artifact, saved = await _saved_session(session)
    export, _created = await SessionExports(session).create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        idempotency_key=f"export-{uuid4().hex}",
    )
    await session.commit()

    stranger = type(user)(email=f"s-{uuid4().hex}@example.com", display_name="S", password_hash="x")
    session.add(stranger)
    await session.flush()
    with pytest.raises(ForbiddenError):
        await download_export_content(
            project_id=project.id,
            export_id=export.id,
            request=_request(),
            user=stranger,
            session=session,
        )


@pytest.mark.asyncio
async def test_media_format_export_stays_undeliverable_until_rendered(
    session: AsyncSession,
) -> None:
    from app.api.v1.editing import download_export_content

    project, user, _shot_row, _artifact, saved = await _saved_session(session)
    service = SessionExports(session)
    export, created = await service.create_session_export(
        project_id=project.id,
        session_id=saved.id,
        requested_by=user.id,
        format="mp4",
        idempotency_key=f"export-{uuid4().hex}",
    )
    await session.commit()
    assert created is True
    # The receipt is created, but it is a request for media, not media yet.
    assert export.format == "mp4"
    assert export.result_artifact_id is None
    with pytest.raises(ValidationAppError) as pending:
        await download_export_content(
            project_id=project.id,
            export_id=export.id,
            request=_request(),
            user=user,
            session=session,
        )
    assert pending.value.details["code"] == "EXPORT_NOT_DELIVERABLE"

    with pytest.raises(ValidationAppError) as unsupported:
        await service.create_session_export(
            project_id=project.id,
            session_id=saved.id,
            requested_by=user.id,
            format="pdf",
        )
    assert unsupported.value.details["code"] == "EXPORT_FORMAT_UNSUPPORTED"


@pytest.mark.asyncio
async def test_unsupported_formats_and_unbound_clips_are_refused(
    session: AsyncSession,
) -> None:
    project, user, _shot_row, _artifact, saved = await _saved_session(session)
    service = SessionExports(session)

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
