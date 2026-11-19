"""Typed research revisions, user decisions and verbatim citations (I4-02)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.assets.research import CitationInput, ResearchConflictError, ResearchService
from app.assets.research_models import ResearchResultRevision
from app.shared.errors import ValidationAppError
from app.storage.minio_store import InMemoryObjectStore


@pytest.fixture
async def research(session):
    actor = User(email=f"research-{uuid4()}@example.com", display_name="R", password_hash="x")
    session.add(actor)
    await session.flush()
    workspace = Workspace(name="Research", owner_user_id=actor.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    store = InMemoryObjectStore()
    files = ProjectFileService(session, store=store, actor=actor, project_id=project.id)
    revision = await files.upload(
        filename="地方志.txt",
        data="古桥始建于明代。\n桥体为石拱结构。".encode(),
        mime_type="text/plain",
        request_key="upload-1",
    )
    await files.extract(revision.id)
    fragments, _total = await files.list_fragments(revision.current_extraction_id, limit=10)
    service = ResearchService(session, actor=actor, project_id=project.id)
    return {
        "session": session,
        "service": service,
        "file_revision_id": revision.id,
        "fragments": fragments,
    }


def _citation(fragment, *, quote: str = "", claim: str = "root") -> CitationInput:
    return CitationInput(
        source_fragment_id=fragment.id,
        file_revision_id=fragment.file_revision_id,
        claim_key=claim,
        quoted_text=quote,
    )


async def test_typed_creation_and_request_replay(research):
    service = research["service"]
    body = {"schema_version": 1, "display_name": "张某", "aliases": ["张公"]}
    receipt = await service.create_result(
        kind="person", body=body, verification="user_asserted",
        citations=[], request_key="create-1",
    )
    assert receipt.result_version == 2 and receipt.revision_number == 1
    assert receipt.origin == "user"
    replay = await service.create_result(
        kind="person", body=body, verification="user_asserted",
        citations=[], request_key="create-1",
    )
    assert replay.revision_id == receipt.revision_id
    with pytest.raises(ResearchConflictError) as reused:
        await service.create_result(
            kind="person", body={"schema_version": 1, "display_name": "李某"},
            verification="user_asserted", citations=[], request_key="create-1",
        )
    assert reused.value.code == "RESEARCH_REQUEST_KEY_REUSED"
    result = await service.read_result(receipt.result_id)
    assert result.current_revision_id == receipt.revision_id and result.version == 2


@pytest.mark.parametrize("kind,body,code", [
    ("person", {"schema_version": 1, "display_name": ""}, "RESEARCH_BODY_INVALID"),
    ("person", {"schema_version": 1, "display_name": "张某", "extra": 1}, "RESEARCH_BODY_INVALID"),
    ("summary", {"schema_version": 1, "display_name": "错形状"}, "RESEARCH_BODY_INVALID"),
    ("timeline", {"schema_version": 1, "items": []}, "RESEARCH_BODY_INVALID"),
    ("event", {"schema_version": 1}, "RESEARCH_BODY_INVALID"),
])
async def test_bodies_are_typed_not_free_json(research, kind, body, code):
    with pytest.raises(ValidationAppError) as failure:
        await research["service"].create_result(
            kind=kind, body=body, verification="unverified", citations=[],
            request_key=f"bad-{uuid4()}",
        )
    assert failure.value.details.get("code") == code


async def test_citations_must_be_verbatim_and_inside_the_fragment(research):
    service = research["service"]
    fragment = research["fragments"][0]
    good = await service.create_result(
        kind="summary",
        body={"schema_version": 1, "text": "古桥始建于明代"},
        verification="unverified",
        citations=[_citation(fragment, quote="古桥始建于明代")],
        request_key="cite-good",
    )
    views = await service.citation_views(good.revision_id)
    assert len(views) == 1 and views[0][2] is True
    with pytest.raises(ValidationAppError) as not_verbatim:
        await service.create_result(
            kind="summary",
            body={"schema_version": 1, "text": "古桥始建于唐代"},
            verification="unverified",
            citations=[_citation(fragment, quote="古桥始建于唐代")],
            request_key="cite-bad-quote",
        )
    assert not_verbatim.value.details.get("code") == "RESEARCH_QUOTE_NOT_VERBATIM"
    with pytest.raises(ValidationAppError) as unknown:
        await service.create_result(
            kind="summary",
            body={"schema_version": 1, "text": "x"},
            verification="unverified",
            citations=[CitationInput(uuid4(), fragment.file_revision_id)],
            request_key="cite-unknown",
        )
    assert unknown.value.details.get("code") == "RESEARCH_FRAGMENT_UNKNOWN"
    with pytest.raises(ValidationAppError) as mismatch:
        await service.create_result(
            kind="summary",
            body={"schema_version": 1, "text": "x"},
            verification="unverified",
            citations=[CitationInput(fragment.id, uuid4())],
            request_key="cite-mismatch",
        )
    assert mismatch.value.details.get("code") == "RESEARCH_FRAGMENT_REVISION_MISMATCH"
    with pytest.raises(ValidationAppError) as locator:
        await service.create_result(
            kind="summary",
            body={"schema_version": 1, "text": "x"},
            verification="unverified",
            citations=[
                CitationInput(
                    fragment.id, fragment.file_revision_id,
                    locator_override={"kind": "paragraph", "char_start": 0, "char_end": 9999},
                )
            ],
            request_key="cite-locator",
        )
    assert locator.value.details.get("code") == "RESEARCH_LOCATOR_OUT_OF_RANGE"


async def test_correction_requires_current_version_and_base(research):
    service = research["service"]
    created = await service.create_result(
        kind="summary", body={"schema_version": 1, "text": "初稿"},
        verification="unverified", citations=[], request_key="corr-create",
    )
    with pytest.raises(ResearchConflictError) as stale:
        await service.append_revision(
            created.result_id, expected_version=1, base_revision_id=created.revision_id,
            body={"schema_version": 1, "text": "旧版本"}, verification="unverified",
            citations=[], request_key="corr-stale",
        )
    assert stale.value.code == "RESEARCH_STALE_VERSION"
    with pytest.raises(ResearchConflictError) as base:
        await service.append_revision(
            created.result_id, expected_version=2, base_revision_id=None,
            body={"schema_version": 1, "text": "旧基线"}, verification="unverified",
            citations=[], request_key="corr-base",
        )
    assert base.value.code == "RESEARCH_STALE_BASE"
    corrected = await service.append_revision(
        created.result_id, expected_version=2, base_revision_id=created.revision_id,
        body={"schema_version": 1, "text": "用户修正"}, verification="user_asserted",
        citations=[], request_key="corr-ok",
    )
    assert corrected.revision_number == 2 and corrected.result_version == 3
    result = await service.read_result(created.result_id)
    assert result.current_revision_id == corrected.revision_id


async def test_accept_and_restore_append_new_revisions_without_rewriting(research):
    service = research["service"]
    created = await service.create_result(
        kind="summary", body={"schema_version": 1, "text": "初稿"},
        verification="unverified", citations=[], request_key="dec-create",
    )
    session = research["session"]
    candidate = ResearchResultRevision(
        project_id=(await service.read_result(created.result_id)).project_id,
        result_id=created.result_id,
        number=2,
        origin="model",
        body={"schema_version": 1, "text": "模型候选"},
        content_hash="0" * 64,
        verification="unverified",
        applied_result_version=None,
        origin_invocation_id=uuid4(),
        output_item_key="item-1",
        request_key="model-candidate-1",
        request_hash="0" * 64,
    )
    session.add(candidate)
    await session.flush()
    accepted = await service.accept_candidate(
        created.result_id, expected_version=2, candidate_revision_id=candidate.id,
        base_revision_id=created.revision_id, request_key="dec-accept",
    )
    assert accepted.origin == "accept" and accepted.revision_number == 3
    assert accepted.result_version == 3
    accepted_revision = await service.read_revision(accepted.revision_id)
    assert accepted_revision.accepts_revision_id == candidate.id
    assert accepted_revision.body["text"] == "模型候选"
    restored = await service.restore(
        created.result_id, expected_version=3, restore_revision_id=created.revision_id,
        base_revision_id=accepted.revision_id, request_key="dec-restore",
    )
    assert restored.origin == "restore" and restored.result_version == 4
    restored_revision = await service.read_revision(restored.revision_id)
    assert restored_revision.restores_revision_id == created.revision_id
    assert restored_revision.body["text"] == "初稿"


async def test_archive_is_metadata_only_and_blocks_new_revisions(research):
    service = research["service"]
    created = await service.create_result(
        kind="summary", body={"schema_version": 1, "text": "归档"},
        verification="unverified", citations=[], request_key="arch-create",
    )
    archived = await service.archive(created.result_id, expected_version=2, archived=True)
    assert archived.archived_at is not None and archived.version == 3
    # Repeating the same decision is idempotent and does not bump the version again.
    again = await service.archive(created.result_id, expected_version=3, archived=True)
    assert again.version == 3
    with pytest.raises(ResearchConflictError) as blocked:
        await service.append_revision(
            created.result_id, expected_version=3, base_revision_id=created.revision_id,
            body={"schema_version": 1, "text": "迟到"}, verification="unverified",
            citations=[], request_key="arch-append",
        )
    assert blocked.value.code == "RESEARCH_RESULT_ARCHIVED"
    results, total = await service.list_results()
    assert results == [] and total == 0
    restored = await service.archive(created.result_id, expected_version=3, archived=False)
    assert restored.archived_at is None and restored.version == 4


async def test_list_filters_by_kind_query_and_suggestions(research):
    service = research["service"]
    await service.create_result(
        kind="person", body={"schema_version": 1, "display_name": "古桥匠人"},
        verification="unverified", citations=[], request_key="list-person",
    )
    await service.create_result(
        kind="place", body={"schema_version": 1, "display_name": "East Ferry"},
        verification="unverified", citations=[], request_key="list-place",
    )
    people, total = await service.list_results(kind="person")
    assert total == 1 and people[0].kind == "person"
    # Portable JSON storage escapes CJK on SQLite; real Chinese matching is proven
    # against PostgreSQL in tests/integration/test_research_results_pg.py.
    found, total = await service.list_results(query="Ferry")
    assert total == 1 and found[0].kind == "place"
    escaped, total = await service.list_results(query="%")
    assert total == 0
    suggestions, total = await service.list_results(view="suggestions")
    assert suggestions == [] and total == 0
