"""HTTP knowledge lifecycle: draft, publish, list and withdraw (I4-03)."""

from __future__ import annotations

from app.shared.security import CSRF_HEADER
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


def test_knowledge_entry_http_lifecycle(api):
    client, _factory = api
    workspace = _register(client)
    _project(client, workspace, "Knowledge")
    csrf = {CSRF_HEADER: _csrf(client)}
    base = {"workspace_id": workspace, "kind": "person", "title": "古桥匠人"}
    created = client.post(
        "/api/v1/knowledge/entries",
        json={
            **base,
            "request_key": "know-http-1",
            "operation": "save_draft",
            "body": {"schema_version": 1, "display_name": "张某"},
            "allowed_uses": ["research"],
            "public_source_notes": [{"label": "地方志"}],
            "source_links": [],
        },
        headers=csrf,
    )
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert receipt["publication_status"] == "draft"
    assert receipt["result_entry_version"] == 2
    entry_id = receipt["entry_id"]
    draft = client.get(f"/api/v1/knowledge/entries/{entry_id}").json()
    assert draft["title"] == "古桥匠人" and draft["publication_status"] == "draft"
    published = client.post(
        f"/api/v1/knowledge/entries/{entry_id}/revisions",
        json={
            "request_key": "know-http-publish",
            "expected_version": 2,
            "operation": "publish",
            "title": "古桥匠人",
            "body": {"schema_version": 1, "display_name": "张某", "description": "明代"},
            "allowed_uses": ["research"],
            "public_source_notes": [],
            "source_links": [],
        },
        headers=csrf,
    )
    assert published.status_code == 201, published.text
    assert published.json()["publication_status"] == "published"
    listing = client.get("/api/v1/knowledge/entries").json()
    assert listing["total"] == 1
    assert listing["items"][0]["summary"] == "张某"
    revisions = client.get(f"/api/v1/knowledge/entries/{entry_id}/revisions").json()
    assert revisions["total"] == 2
    assert [item["operation"] for item in revisions["items"]] == ["publish", "save_draft"]
    withdrawn = client.post(
        f"/api/v1/knowledge/entries/{entry_id}/withdraw",
        json={"request_key": "know-http-withdraw", "expected_version": 3},
        headers=csrf,
    )
    assert withdrawn.status_code == 201, withdrawn.text
    assert withdrawn.json()["publication_status"] == "withdrawn"
    assert client.get("/api/v1/knowledge/entries").json()["total"] == 0
    assert client.get("/api/v1/knowledge/entries?status=withdrawn").json()["total"] == 1
    replay = client.post(
        f"/api/v1/knowledge/entries/{entry_id}/withdraw",
        json={"request_key": "know-http-withdraw", "expected_version": 3},
        headers=csrf,
    )
    assert replay.status_code == 201
    assert replay.json()["revision_id"] == withdrawn.json()["revision_id"]
    stale = client.post(
        f"/api/v1/knowledge/entries/{entry_id}/revisions",
        json={
            "request_key": "know-http-stale",
            "expected_version": 2,
            "operation": "publish",
            "title": "迟到",
            "body": {"schema_version": 1, "display_name": "张某"},
            "allowed_uses": ["research"],
            "public_source_notes": [],
            "source_links": [],
        },
        headers=csrf,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "KNOWLEDGE_STALE_VERSION"
    assert client.get("/api/v1/knowledge/entries").json()["total"] == 0


def test_knowledge_reference_http_lifecycle(api):
    client, _factory = api
    workspace = _register(client)
    project = _project(client, workspace, "References")
    csrf = {CSRF_HEADER: _csrf(client)}
    entry = client.post(
        "/api/v1/knowledge/entries",
        json={
            "request_key": "ref-entry-1",
            "workspace_id": workspace,
            "kind": "person",
            "operation": "publish",
            "title": "古桥匠人",
            "body": {"schema_version": 1, "display_name": "张某"},
            "allowed_uses": ["research", "creation"],
            "public_source_notes": [],
            "source_links": [],
        },
        headers=csrf,
    )
    assert entry.status_code == 201, entry.text
    receipt = entry.json()
    base = f"/api/v1/projects/{project}/knowledge-references"
    created = client.post(
        base,
        json={
            "knowledge_entry_id": receipt["entry_id"],
            "knowledge_revision_id": receipt["revision_id"],
            "allowed_use": "research",
        },
        headers=csrf,
    )
    assert created.status_code == 201, created.text
    reference = created.json()
    assert reference["availability"] == "published" and reference["version"] == 1
    replay = client.post(
        base,
        json={
            "knowledge_entry_id": receipt["entry_id"],
            "knowledge_revision_id": receipt["revision_id"],
            "allowed_use": "research",
        },
        headers=csrf,
    )
    assert replay.status_code == 200 and replay.json()["id"] == reference["id"]
    listing = client.get(base).json()
    assert listing["total"] == 1 and listing["items"][0]["availability"] == "published"
    detached = client.patch(
        f"{base}/{reference['id']}",
        json={"expected_version": 1, "attached": False},
        headers=csrf,
    )
    assert detached.status_code == 200 and detached.json()["detached_at"] is not None
    assert client.get(base).json()["total"] == 0
    assert client.get(f"{base}?active=false").json()["total"] == 1
    reattached = client.patch(
        f"{base}/{reference['id']}",
        json={"expected_version": 2, "attached": True},
        headers=csrf,
    )
    assert reattached.status_code == 200 and reattached.json()["detached_at"] is None
    draft = client.post(
        "/api/v1/knowledge/entries",
        json={
            "request_key": "ref-entry-draft",
            "workspace_id": workspace,
            "kind": "summary",
            "operation": "save_draft",
            "title": "草稿",
            "body": {"schema_version": 1, "text": "草稿"},
            "allowed_uses": ["research"],
            "public_source_notes": [],
            "source_links": [],
        },
        headers=csrf,
    )
    assert draft.status_code == 201
    refused = client.post(
        base,
        json={
            "knowledge_entry_id": draft.json()["entry_id"],
            "knowledge_revision_id": draft.json()["revision_id"],
            "allowed_use": "research",
        },
        headers=csrf,
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "KNOWLEDGE_NOT_PUBLISHED"
