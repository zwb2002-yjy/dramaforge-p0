"""HTTP research result lifecycle over the real service and extraction evidence."""

from __future__ import annotations

import asyncio

from app.api.v1 import project_files
from app.shared.security import CSRF_HEADER
from app.storage.minio_store import InMemoryObjectStore
from app.workers.project_files import process_project_files
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


def _research_source(client, project: str, store, factory) -> tuple[str, str, str]:
    """Upload one TXT through the real entry and return (fragment_id, file_revision_id)."""
    path = f"/api/v1/projects/{project}/files"
    response = client.post(
        path,
        params={"filename": "地方志.txt", "request_key": "research-upload"},
        content="古桥始建于明代。\n桥体为石拱结构。".encode(),
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    source = response.json()
    asyncio.run(process_project_files(factory, store=store))
    current = client.get(f"/api/v1/projects/{project}/files/{source['id']}").json()
    fragments = client.get(
        f"/api/v1/projects/{project}/extractions/{current['current_extraction_id']}/fragments"
    ).json()
    return (
        fragments["items"][0]["id"],
        source["revision_id"],
        fragments["items"][0]["extraction_id"],
    )


def test_research_result_lifecycle_and_typed_validation(api, monkeypatch):
    client, factory = api
    store = InMemoryObjectStore()
    monkeypatch.setattr(project_files, "get_object_store", lambda: store)
    workspace = _register(client)
    project = _project(client, workspace, "Research")
    fragment_id, file_revision_id, extraction_id = _research_source(
        client, project, store, factory
    )
    base = f"/api/v1/projects/{project}/research-results"
    csrf = {CSRF_HEADER: _csrf(client)}

    created = client.post(
        base,
        json={
            "request_key": "create-person",
            "kind": "person",
            "body": {"schema_version": 1, "display_name": "张某", "aliases": ["张公"]},
            "verification": "user_asserted",
            "citations": [
                {
                    "source_fragment_id": fragment_id,
                    "file_revision_id": file_revision_id,
                    "claim_key": "root",
                    "quoted_text": "古桥始建于明代。",
                }
            ],
        },
        headers=csrf,
    )
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert receipt["result_version"] == 2 and receipt["revision_number"] == 1
    result_id = receipt["result_id"]
    # Same key and payload returns the original receipt.
    replay = client.post(
        base,
        json={
            "request_key": "create-person",
            "kind": "person",
            "body": {"schema_version": 1, "display_name": "张某", "aliases": ["张公"]},
            "verification": "user_asserted",
            "citations": [
                {
                    "source_fragment_id": fragment_id,
                    "file_revision_id": file_revision_id,
                    "claim_key": "root",
                    "quoted_text": "古桥始建于明代。",
                }
            ],
        },
        headers=csrf,
    )
    assert replay.status_code == 201 and replay.json()["revision_id"] == receipt["revision_id"]
    listed = client.get(base).json()
    assert listed["total"] == 1 and listed["items"][0]["current"]["summary"] == "张某"
    read = client.get(f"{base}/{result_id}").json()
    assert read["version"] == 2 and read["current_revision_id"] == receipt["revision_id"]
    revisions = client.get(f"{base}/{result_id}/revisions").json()
    assert revisions["total"] == 1 and revisions["items"][0]["origin"] == "user"
    revision = client.get(
        f"/api/v1/projects/{project}/research-revisions/{receipt['revision_id']}"
    ).json()
    assert revision["citations"][0]["quoted_text"] == "古桥始建于明代。"
    assert revision["citations"][0]["source_available"] is True

    corrected = client.post(
        f"{base}/{result_id}/revisions",
        json={
            "request_key": "correct-1",
            "expected_version": 2,
            "base_revision_id": receipt["revision_id"],
            "body": {"schema_version": 1, "display_name": "张某", "description": "用户修正"},
            "verification": "user_asserted",
            "citations": [],
        },
        headers=csrf,
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["revision_number"] == 2
    stale = client.post(
        f"{base}/{result_id}/revisions",
        json={
            "request_key": "correct-stale",
            "expected_version": 2,
            "base_revision_id": corrected.json()["revision_id"],
            "body": {"schema_version": 1, "display_name": "迟到"},
            "verification": "unverified",
            "citations": [],
        },
        headers=csrf,
    )
    assert stale.status_code == 409 and stale.json()["code"] == "RESEARCH_STALE_VERSION"

    restored = client.post(
        f"{base}/{result_id}/restore",
        json={
            "request_key": "restore-1",
            "expected_version": 3,
            "base_revision_id": corrected.json()["revision_id"],
            "restore_revision_id": receipt["revision_id"],
        },
        headers=csrf,
    )
    assert restored.status_code == 201 and restored.json()["origin"] == "restore"
    archived = client.patch(
        f"{base}/{result_id}",
        json={"expected_version": 4, "archived": True},
        headers=csrf,
    )
    assert archived.status_code == 200 and archived.json()["archived_at"] is not None
    blocked = client.post(
        f"{base}/{result_id}/revisions",
        json={
            "request_key": "after-archive",
            "expected_version": 5,
            "base_revision_id": restored.json()["revision_id"],
            "body": {"schema_version": 1, "display_name": "迟到"},
            "verification": "unverified",
            "citations": [],
        },
        headers=csrf,
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "RESEARCH_RESULT_ARCHIVED"

    invalid_body = client.post(
        base,
        json={
            "request_key": "invalid-body",
            "kind": "person",
            "body": {"schema_version": 1, "display_name": ""},
            "verification": "unverified",
            "citations": [],
        },
        headers=csrf,
    )
    assert invalid_body.status_code == 422
    assert invalid_body.json()["code"] == "VALIDATION_ERROR"
    bad_quote = client.post(
        base,
        json={
            "request_key": "invalid-quote",
            "kind": "summary",
            "body": {"schema_version": 1, "text": "伪引文"},
            "verification": "unverified",
            "citations": [
                {
                    "source_fragment_id": fragment_id,
                    "file_revision_id": file_revision_id,
                    "claim_key": "root",
                    "quoted_text": "并不存在的原文",
                }
            ],
        },
        headers=csrf,
    )
    assert bad_quote.status_code == 422
    assert bad_quote.json()["details"]["code"] == "RESEARCH_QUOTE_NOT_VERBATIM"


def test_analysis_preview_reports_blockers_without_calling_a_model(api, monkeypatch):
    from app.director.invocation_models import DirectorInvocation
    from sqlalchemy import func, select

    client, factory = api
    store = InMemoryObjectStore()
    monkeypatch.setattr(project_files, "get_object_store", lambda: store)
    workspace = _register(client)
    project = _project(client, workspace, "Preview")
    _fragment_id, file_revision_id, extraction_id = _research_source(
        client, project, store, factory
    )
    path = f"/api/v1/projects/{project}/file-revisions/{file_revision_id}/analysis-preview"
    response = client.post(
        path,
        json={"source_extraction_id": extraction_id, "expected_file_version": 1},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["preview_fingerprint"]) == 64
    assert payload["max_model_calls"] == 1
    assert payload["missing_categories"] == [
        "summary", "person", "place", "event", "timeline", "cultural_clue",
    ]
    assert "text_model_unavailable" in payload["blockers"]
    assert "source_use_blocked" in payload["blockers"]
    assert payload["model_identity"] is None
    assert payload["source_use_summary"]["allowed"] is False
    # Repeating the same preview is stable and still writes nothing.
    again = client.post(
        path,
        json={"source_extraction_id": extraction_id, "expected_file_version": 1},
    )
    assert again.json()["preview_fingerprint"] == payload["preview_fingerprint"]

    async def count_invocations() -> int:
        async with factory() as session:
            return int(
                await session.scalar(select(func.count()).select_from(DirectorInvocation)) or 0
            )

    assert asyncio.run(count_invocations()) == 0
    stale = client.post(
        path,
        json={"source_extraction_id": extraction_id, "expected_file_version": 2},
    )
    assert stale.status_code == 422
    assert stale.json()["details"]["code"] == "RESEARCH_PREVIEW_STALE"


def test_analysis_reads_expose_manifest_and_results(api, monkeypatch):
    from uuid import UUID, uuid4

    from app.access.models import User, Workspace
    from app.assets.research import CitationInput
    from app.assets.research_analysis import (
        CategoryOutcome,
        FindingInput,
        ResearchAnalysisService,
    )
    from app.assets.research_models import RESEARCH_KINDS

    client, factory = api
    store = InMemoryObjectStore()
    monkeypatch.setattr(project_files, "get_object_store", lambda: store)
    workspace = _register(client)
    project = _project(client, workspace, "Analysis")
    fragment_id, file_revision_id, extraction_id = _research_source(
        client, project, store, factory
    )

    async def publish() -> str:
        async with factory() as session:
            ws = await session.get(Workspace, UUID(workspace))
            assert ws is not None
            actor = await session.get(User, ws.owner_user_id)
            assert actor is not None
            session.info["selected_workspace_id"] = UUID(workspace)
            service = ResearchAnalysisService(
                session, actor=actor, project_id=UUID(project)
            )
            outcomes = {
                kind: CategoryOutcome("none", [], 0) for kind in RESEARCH_KINDS
            }
            outcomes["summary"] = CategoryOutcome("findings", [UUID(fragment_id)], 1)
            result = await service.publish(
                UUID(file_revision_id),
                source_extraction_id=UUID(extraction_id),
                request_key="api-analysis",
                request_hash="a" * 64,
                category_outcomes=outcomes,
                findings=[
                    FindingInput(
                        kind="summary",
                        body={"schema_version": 1, "text": "古桥始建于明代"},
                        citations=[
                            CitationInput(
                                UUID(fragment_id),
                                UUID(file_revision_id),
                                quoted_text="古桥始建于明代。",
                            )
                        ],
                    )
                ],
                invocation_ids=[uuid4()],
                coverage={"schema_version": 1, "complete": True},
            )
            await session.commit()
            return str(result.analysis_id)

    analysis_id = asyncio.run(publish())
    listing = client.get(
        f"/api/v1/projects/{project}/file-revisions/{file_revision_id}/analyses"
    ).json()
    assert listing["total"] == 1
    assert listing["items"][0]["category_outcomes"]["summary"]["outcome"] == "findings"
    detail = client.get(f"/api/v1/projects/{project}/analyses/{analysis_id}").json()
    assert detail["manifest_hash"]
    assert detail["results"][0]["disposition"] == "current"
    page = client.get(
        f"/api/v1/projects/{project}/analyses/{analysis_id}/results"
    ).json()
    assert page["total"] == 1 and page["items"][0]["category"] == "summary"
    missing = client.get(
        f"/api/v1/projects/{'0' * 8}-0000-0000-0000-000000000000/analyses/{analysis_id}"
    )
    assert missing.status_code == 404
