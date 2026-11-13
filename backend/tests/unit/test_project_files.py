"""Original history, source isolation and per-file processing over real domain rows."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.project_files import ProjectFileService
from app.events.models import OutboxEvent
from app.shared.errors import ConflictError, NotFoundError
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import func, select


@pytest.fixture
async def sources(session):
    actor = User(email=f"sources-{uuid4()}@example.com", display_name="Reader", password_hash="x")
    session.add(actor)
    await session.flush()
    workspace = Workspace(name="Research", owner_user_id=actor.id)
    session.add(workspace)
    await session.flush()
    projects = [Project(workspace_id=workspace.id, name=name, aspect_ratio="16:9", budget_limit=0)
                for name in ("First", "Second")]
    session.add_all(projects)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    store = InMemoryObjectStore()
    return tuple(ProjectFileService(session, store=store, actor=actor, project_id=project.id)
                 for project in projects)


async def upload(service, key="upload-1", **changes):
    return await service.upload(**{
        "filename": "地方志.txt", "data": "第一段\n\n古桥待考".encode(),
        "mime_type": "text/plain", "request_key": key, **changes,
    })


async def test_original_revision_and_outbox_share_upload_identity(session, sources):
    first, _ = sources
    revision = await upload(first)
    await session.commit()
    replay = await upload(first)
    assert replay.id == revision.id
    assert await session.scalar(select(func.count(ProjectFile.id))) == 1
    assert await session.scalar(select(func.count(ProjectFileRevision.id))) == 1
    assert await session.scalar(select(func.count(OutboxEvent.id))) == 1
    original = await first.store.get_bytes(object_key=revision.object_key)
    assert original == "第一段\n\n古桥待考".encode()
    parsed = await first.extract(revision.id)
    assert parsed.status == "parsed"
    assert parsed.excerpts[1] == {"text": "古桥待考", "location": {"line": 3}}
    assert await first.store.get_bytes(object_key=revision.object_key) == original
    with pytest.raises(ConflictError):
        await upload(first, data=b"different")


async def test_duplicate_bytes_keep_project_associations_and_results_private(session, sources):
    first, second = sources
    a = await upload(first)
    b = await upload(first, key="separate-association")
    c = await upload(second)
    assert a.id != b.id and a.file_id != b.file_id and a.object_key == b.object_key
    assert a.object_key != c.object_key and a.project_id != c.project_id
    await first.extract(a.id)
    assert b.status == c.status == "pending"
    with pytest.raises(NotFoundError):
        await second.read_revision(a.id)
    with pytest.raises(NotFoundError):
        await second.upload(filename="a.txt", data=b"x", mime_type="text/plain",
                            request_key="foreign", file_id=a.file_id, expected_version=1)


async def test_old_extraction_cannot_replace_latest_revision_and_unlink_retains_originals(
    session, sources,
):
    first, _ = sources
    old = await upload(first)
    latest = await upload(first, key="update", file_id=old.file_id,
                          expected_version=1, data=b"new source")
    await first.extract(old.id)
    item, _ = await first.read_revision(old.id)
    assert item.content_version == latest.number == 2 and latest.status == "pending"
    with pytest.raises(ConflictError):
        await upload(first, key="stale-update", file_id=old.file_id, expected_version=1)
    await first.unlink(old.file_id, expected_version=2)
    assert await first.list_files() == []
    assert (await first.read_revision(old.id))[0].detached_at is not None
    assert await first.store.get_bytes(object_key=old.object_key)
    assert (await first.extract(latest.id)).status == "pending"
    with pytest.raises(ConflictError):
        await first.retry_extraction(latest.id, request_key="unlinked")
    assert await session.scalar(select(func.count(ProjectFileRevision.id))) == 2


async def test_failed_file_is_independent_and_retry_is_idempotent(session, sources):
    first, _ = sources
    invalid = await upload(first, filename="scan.pdf", data=b"%PDF")
    valid = await upload(first, key="valid")
    await first.extract(invalid.id)
    assert invalid.status == "failed" and invalid.error_code == "source_format_unsupported"
    assert (await first.extract(valid.id)).status == "parsed"
    before = await session.scalar(select(func.count(OutboxEvent.id)))
    await first.retry_extraction(invalid.id, request_key="retry-1")
    await first.retry_extraction(invalid.id, request_key="retry-1")
    assert invalid.status == "pending"
    assert await session.scalar(select(func.count(OutboxEvent.id))) == before + 1
    await first.extract(invalid.id)
    assert invalid.status == "failed"
    await first.retry_extraction(invalid.id, request_key="retry-1")
    assert invalid.status == "failed"
    assert await session.scalar(select(func.count(OutboxEvent.id))) == before + 1
    await first.retry_extraction(invalid.id, request_key="retry-2")
    assert await session.scalar(select(func.count(OutboxEvent.id))) == before + 2
    assert valid.status == "parsed"


async def test_upload_rollback_does_not_leave_partial_database_admission(session, sources):
    first, _ = sources
    revision = await upload(first)
    object_key = revision.object_key
    await session.rollback()
    assert await session.scalar(select(func.count(ProjectFile.id))) == 0
    assert await session.scalar(select(func.count(OutboxEvent.id))) == 0
    # Content-addressed bytes may outlive a rolled-back association. Never delete
    # this key in compensation: another committed source may share the same bytes.
    assert await first.store.get_bytes(object_key=object_key)
