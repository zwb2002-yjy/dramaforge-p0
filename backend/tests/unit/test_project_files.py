"""Original history, source isolation and per-file processing over real domain rows."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.models import ProjectFile, ProjectFileRevision
from app.assets.project_files import ProjectFileService, current_processor_profile
from app.assets.source_models import SourceExtraction
from app.events.models import OutboxEvent
from app.shared.errors import AppError, ConflictError, NotFoundError
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
    assert parsed.current_extraction_id is not None
    fragments, total = await first.list_fragments(parsed.current_extraction_id)
    assert total == 2
    assert [item.text_content for item in fragments] == ["第一段", "古桥待考"]
    assert fragments[1].locator == {
        "kind": "paragraph", "container_key": "text-lines", "paragraph_start": 2,
        "paragraph_end": 3, "char_start": 0, "char_end": len("古桥待考"),
    }
    assert fragments[1].locator_kind == "paragraph"
    assert fragments[1].extraction_method == "native_text"
    assert fragments[1].processor_ref == "native-text-v1"
    assert fragments[1].evidence_meta["original_location"] == {"line": 3}
    extraction = await first.read_extraction(parsed.current_extraction_id)
    assert extraction.extraction_schema_version == 2
    assert extraction.coverage["complete"] is True
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
    with pytest.raises(AppError) as unavailable:
        await first.accept_extraction(
            latest.id,
            action="retry",
            request_key="unlinked",
            expected_file_version=2,
            expected_attempt=latest.attempt,
            expected_extraction_id=None,
            processor_profile_revision=current_processor_profile(),
        )
    assert unavailable.value.code == "SOURCE_UNAVAILABLE"
    assert await session.scalar(select(func.count(ProjectFileRevision.id))) == 2


async def test_failed_file_is_independent_and_retry_acceptance_is_idempotent(session, sources):
    first, _ = sources
    invalid = await upload(first, filename="scan.pdf", data=b"%PDF")
    valid = await upload(first, key="valid")
    await first.extract(invalid.id)
    assert invalid.status == "failed" and invalid.error_code == "source_pdf_invalid"
    assert (await first.extract(valid.id)).status == "parsed"
    item, _ = await first.read_revision(invalid.id)
    profile = current_processor_profile()
    original_attempt = invalid.attempt
    before = await session.scalar(select(func.count(OutboxEvent.id)))

    async def accept(key: str, *, attempt: int = original_attempt, profile_value: str = profile):
        return await first.accept_extraction(
            invalid.id,
            action="retry",
            request_key=key,
            expected_file_version=item.version,
            expected_attempt=attempt,
            expected_extraction_id=None,
            processor_profile_revision=profile_value,
        )

    acceptance = await accept("retry-1")
    assert acceptance.accepted_attempt == 2 and acceptance.action == "retry"
    assert invalid.status == "pending" and invalid.attempt == 2
    assert await session.scalar(select(func.count(OutboxEvent.id))) == before + 1
    # Same key and payload replay the original receipt without a second event.
    replay = await accept("retry-1")
    assert replay.event_id == acceptance.event_id
    assert await session.scalar(select(func.count(OutboxEvent.id))) == before + 1
    with pytest.raises(AppError) as reused:
        await accept("retry-1", attempt=original_attempt + 5)
    assert reused.value.code == "SOURCE_REQUEST_KEY_REUSED"
    with pytest.raises(AppError) as drift:
        await accept("retry-drift", profile_value="0" * 64)
    assert drift.value.code == "SOURCE_PROFILE_DRIFT"
    # The worker still fails on the same invalid document; only an explicit accept
    # can move the attempt forward again.
    await first.extract(invalid.id)
    assert invalid.status == "failed"
    second = await accept("retry-2", attempt=2)
    assert second.accepted_attempt == 3
    assert await session.scalar(select(func.count(OutboxEvent.id))) == before + 2
    assert valid.status == "parsed"
    with pytest.raises(AppError) as conflict:
        await first.accept_extraction(
            valid.id,
            action="retry",
            request_key="retry-valid",
            expected_file_version=item.version,
            expected_attempt=1,
            expected_extraction_id=None,
            processor_profile_revision=profile,
        )
    assert conflict.value.code == "SOURCE_STATE_CONFLICT"


async def test_reparse_keeps_the_previous_snapshot_until_the_new_one_succeeds(session, sources):
    first, _ = sources
    revision = await upload(first)
    await first.extract(revision.id)
    first_extraction = revision.current_extraction_id
    assert first_extraction is not None
    item, _ = await first.read_revision(revision.id)
    profile = current_processor_profile()
    acceptance = await first.accept_extraction(
        revision.id,
        action="reparse",
        request_key="reparse-1",
        expected_file_version=item.version,
        expected_attempt=1,
        expected_extraction_id=first_extraction,
        processor_profile_revision=profile,
    )
    assert acceptance.accepted_attempt == 2 and acceptance.action == "reparse"
    assert revision.status == "pending"
    # The old successful snapshot stays current until the new attempt publishes.
    assert revision.current_extraction_id == first_extraction
    assert (await first.read_extraction(first_extraction)).coverage["complete"] is True
    with pytest.raises(AppError) as stale:
        await first.accept_extraction(
            revision.id,
            action="reparse",
            request_key="reparse-2",
            expected_file_version=item.version,
            expected_attempt=2,
            expected_extraction_id=first_extraction,
            processor_profile_revision=profile,
        )
    assert stale.value.code == "SOURCE_STATE_CONFLICT"
    await first.extract(revision.id)
    assert revision.status == "parsed"
    assert revision.current_extraction_id != first_extraction
    assert await session.scalar(select(func.count(SourceExtraction.id))) == 2


async def test_worker_refuses_a_drifted_or_legacy_processor_profile(session, sources):
    first, _ = sources
    drifted = await upload(first, filename="a.txt", data=b"drifted")
    drifted.processor_profile_revision = "0" * 64
    legacy = await upload(first, filename="b.txt", data=b"legacy", key="legacy")
    legacy.processor_profile_revision = None
    await session.commit()
    await first.extract(drifted.id)
    await first.extract(legacy.id)
    assert drifted.status == "failed" and drifted.error_code == "source_profile_drift"
    assert legacy.status == "failed" and legacy.error_code == "source_profile_legacy"
    assert await session.scalar(select(func.count(SourceExtraction.id))) == 0


async def test_completed_extraction_is_immutable_and_reprocessing_is_idempotent(session, sources):
    first, _ = sources
    revision = await upload(first)
    await first.extract(revision.id)
    extraction_id = revision.current_extraction_id
    fragments, total = await first.list_fragments(extraction_id)
    assert len(fragments) == total == 2
    before = await session.scalar(select(func.count(SourceExtraction.id)))
    # A duplicate delivery after success never overwrites the published snapshot.
    assert (await first.extract(revision.id)).current_extraction_id == extraction_id
    assert await session.scalar(select(func.count(SourceExtraction.id))) == before
    repeated, repeated_total = await first.list_fragments(extraction_id)
    assert repeated_total == total
    assert [item.id for item in repeated] == [item.id for item in fragments]


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


def _pdf_pages(count: int) -> bytes:
    """A real multi-page PDF with a text layer, so poppler reads actual pages."""
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode())
    font_object = 3 + count * 2
    for index in range(count):
        stream = f"BT /F1 18 Tf 20 100 Td (Page {index + 1}) Tj ET".encode()
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
                f"/Contents {4 + index * 2} 0 R /Resources << /Font << /F1 "
                f"{font_object} 0 R >> >> >>"
            ).encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


async def test_pdf_blocks_are_resumable_receipts_bound_to_the_attempt(session, sources):
    first, _ = sources
    revision = await upload(
        first,
        filename="长报告.pdf",
        data=_pdf_pages(30),
        mime_type="application/pdf",
    )
    await first.extract(revision.id)
    assert revision.status == "parsed"
    extraction_id = revision.current_extraction_id
    fragments, total = await first.list_fragments(extraction_id, limit=200)
    assert total == 30
    assert [item.locator["page_start"] for item in fragments] == list(range(30))
    assert {item.locator_kind for item in fragments} == {"page_region"}
    assert {item.processor_ref for item in fragments} == {"pdftotext"}
    store_keys = first.store.keys()
    blocks = [key for key in store_keys if "/source-blocks/" in key]
    assert len(blocks) == 2  # 25 pages per block
    extraction = await first.read_extraction(extraction_id)
    assert extraction.coverage["units_total"] == 30
    assert extraction.coverage["complete"] is True
    # A duplicate delivery of the accepted attempt reuses the verified receipts.
    assert (await first.extract(revision.id)).current_extraction_id == extraction_id
    replayed_keys = first.store.keys()
    assert len([key for key in replayed_keys if "/source-blocks/" in key]) == 2
    # A new attempt never reuses the previous attempt's receipts or snapshot.
    revision.status = "pending"
    revision.attempt += 1
    await session.commit()
    await first.extract(revision.id)
    assert revision.current_extraction_id != extraction_id
    attempt_keys = first.store.keys()
    assert len([key for key in attempt_keys if "/source-blocks/" in key]) == 4
    assert await session.scalar(select(func.count(SourceExtraction.id))) == 2
