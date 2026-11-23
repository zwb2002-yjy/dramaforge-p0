"""Owner-wide knowledge reads use safe content across workspaces, including old snapshots."""

from uuid import UUID, uuid4

import httpx
from app.access.models import Workspace
from app.assets.knowledge_models import KnowledgeEntry, KnowledgeRevision, ProjectKnowledgeReference
from app.assets.research_bodies import content_hash
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_owner_scoped_knowledge_and_legacy_projections(http_agent):
    a = http_agent
    path = "/api/v1/knowledge/entries"
    other_ws = {"X-Workspace-Id": str(a.other_workspace_id)}
    marker = "fixture-sensitive-marker"
    private_id = str(uuid4())
    note = {"label": "目录", "public_url": "https://catalog.example.org/books?page=2#intro"}
    private_note = {**note, "public_url": f"https://catalog.example.org/books?signature={marker}"}

    def body(**values):
        return {
            "workspace_id": str(a.workspace_id),
            "request_key": str(uuid4()),
            "kind": "event",
            "operation": "publish",
            "title": "灯会",
            "body": {"schema_version": 1, "description": "桥边"},
            "allowed_uses": ["research"],
            "public_source_notes": [note],
            **values,
        }

    participant = await a.client.post(
        path,
        headers=a.headers,
        json=body(
            kind="person",
            body={"display_name": "叙述者"},
            title="叙述者",
        ),
    )
    assert participant.status_code == 201, participant.text
    person_id = participant.json()["entry_id"]
    good = body(body={"description": "桥边", "participant_entry_ids": [person_id]})
    created = await a.client.post(path, headers=a.headers, json=good)
    assert created.status_code == 201, created.text
    entry_id = created.json()["entry_id"]
    rev_path = f"{path}/{entry_id}/revisions"
    detail = (await a.client.get(rev_path, headers=other_ws)).json()["items"][0]
    assert detail["body"]["participant_entry_ids"] == [person_id]
    assert detail["public_source_notes"][0]["public_url"] == note["public_url"]
    assert detail["shared_content_state"] == "complete"
    draft = await a.client.post(path, headers=a.headers, json=body(operation="save_draft"))
    assert draft.status_code == 201
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=a.app), base_url="http://testserver"
    ) as outsider:
        reg = await outsider.post(
            "/api/v1/auth/register",
            json={
                "email": f"other-{uuid4()}@example.com",
                "password": "Synthetic-library-2026",
                "display_name": "Other",
            },
        )
        assert reg.status_code == 201, reg.text
        workspace = (await outsider.get("/api/v1/workspaces")).json()[0]["id"]
        headers = {
            "X-Workspace-Id": workspace,
            "X-CSRF-Token": (await outsider.get("/api/v1/auth/csrf")).json()["csrf_token"],
        }
        foreign = await outsider.post(path, headers=headers, json=body(workspace_id=workspace))
        assert foreign.status_code == 201, foreign.text
        assert (await outsider.get(rev_path, headers=headers)).status_code == 404
    with Session(a.database.engine) as seed:
        before = seed.scalar(select(func.count()).select_from(KnowledgeRevision))
    for invalid in [
        body(body={"description": "桥边", "related_person_ids": [private_id]}),
        body(body={"description": "桥边", "related_entry_ids": [draft.json()["entry_id"]]}),
        body(body={"description": "桥边", "place_entry_ids": [foreign.json()["entry_id"]]}),
        body(public_source_notes=[private_note]),
        body(
            public_source_notes=[
                {"label": "地图", "locator_note": f"projects/{private_id}/original.png"}
            ]
        ),
        body(title=f"credential={marker}"),
    ]:
        response = await a.client.post(path, headers=a.headers, json=invalid)
        assert response.status_code == 422, response.text
        assert marker not in response.text and private_id not in response.text
    append = body(public_source_notes=[private_note])
    append.pop("workspace_id")
    append.pop("kind")
    response = await a.client.post(
        rev_path, headers=a.headers, json={**append, "expected_version": 2}
    )
    assert response.status_code == 422 and marker not in response.text
    with Session(a.database.engine) as seed:
        assert seed.scalar(select(func.count()).select_from(KnowledgeRevision)) == before
        owner = seed.get(Workspace, a.workspace_id).owner_user_id
        legacy = KnowledgeEntry(
            owner_user_id=owner,
            workspace_id=a.workspace_id,
            kind="event",
            version=1,
            publication_status="draft",
        )
        seed.add(legacy)
        seed.flush()
        original = {
            "schema_version": 1,
            "description": "可共享的灯会",
            "related_person_ids": [private_id],
        }
        rev = KnowledgeRevision(
            owner_user_id=owner,
            entry_id=legacy.id,
            number=1,
            title="旧知识",
            body=original,
            content_hash=content_hash(original),
            allowed_uses=["research", "creation"],
            public_source_notes=[note, private_note],
            operation="publish",
            publication_status="published",
            expected_entry_version=1,
            result_entry_version=2,
            request_key=str(uuid4()),
            request_hash="a" * 64,
        )
        seed.add(rev)
        seed.flush()
        legacy.publication_status = "published"
        legacy.version = 2
        legacy.current_revision_id = rev.id
        seed.flush()
        pin = ProjectKnowledgeReference(
            project_id=a.project_id,
            workspace_id=a.workspace_id,
            owner_user_id=owner,
            knowledge_entry_id=legacy.id,
            knowledge_revision_id=rev.id,
            allowed_use="research",
            version=1,
        )
        seed.add(pin)
        withheld = KnowledgeEntry(
            owner_user_id=owner,
            workspace_id=a.workspace_id,
            kind="event",
            version=1,
            publication_status="draft",
        )
        seed.add(withheld)
        seed.flush()
        hidden_body = {"schema_version": 1, "description": f"credential={marker}"}
        hidden_rev = KnowledgeRevision(
            owner_user_id=owner,
            entry_id=withheld.id,
            number=1,
            title="待核对的旧记录",
            body=hidden_body,
            content_hash=content_hash(hidden_body),
            allowed_uses=["research"],
            public_source_notes=[],
            operation="publish",
            publication_status="published",
            expected_entry_version=1,
            result_entry_version=2,
            request_key=str(uuid4()),
            request_hash="b" * 64,
        )
        seed.add(hidden_rev)
        seed.flush()
        assert marker in seed.scalar(
            select(KnowledgeRevision.search_text).where(KnowledgeRevision.id == hidden_rev.id)
        )
        withheld.publication_status = "published"
        withheld.version = 2
        withheld.current_revision_id = hidden_rev.id
        withheld_id = withheld.id
        legacy_id, rev_id = legacy.id, rev.id
        seed.commit()
    history = f"{path}/{legacy_id}/revisions"
    for url in (path, f"{path}/{legacy_id}", history):
        r = await a.client.get(url, headers=other_ws)
        assert r.status_code == 200, r.text
        assert marker not in r.text and private_id not in r.text
    view = (await a.client.get(history, headers=other_ws)).json()["items"][0]
    assert (
        view["body"]["description"] == "可共享的灯会" and "related_person_ids" not in view["body"]
    )
    assert view["shared_content_state"] == "filtered" and len(view["public_source_notes"]) == 1
    pins = f"/api/v1/projects/{a.project_id}/knowledge-references"
    listing = (await a.client.get(pins)).json()
    assert listing["items"][0]["availability"] == "restricted"
    for hidden_query in (private_id, marker):
        search = await a.client.get(path, headers=other_ws, params={"q": hidden_query})
        assert search.json() == {"items": [], "total": 0, "next_offset": None}
    found = (await a.client.get(path, headers=other_ws, params={"q": "可共享的灯会"})).json()
    assert found["total"] == 1 and found["items"][0]["id"] == str(legacy_id)
    hidden = (await a.client.get(f"{path}/{withheld_id}/revisions", headers=other_ws)).json()
    assert hidden["items"][0]["shared_content_state"] == "unavailable"
    assert hidden["items"][0]["body"] == {}
    new_pin = await a.client.post(
        pins,
        headers=a.headers,
        json={
            "knowledge_entry_id": str(legacy_id),
            "knowledge_revision_id": str(rev_id),
            "allowed_use": "creation",
        },
    )
    assert new_pin.status_code == 409, new_pin.text
    pin_path = f"{pins}/{listing['items'][0]['id']}"
    detached = await a.client.patch(
        pin_path, headers=a.headers, json={"expected_version": 1, "attached": False}
    )
    assert detached.status_code == 200, detached.text
    reattached = await a.client.patch(
        pin_path, headers=a.headers, json={"expected_version": 2, "attached": True}
    )
    assert reattached.status_code == 409, reattached.text
    withdrawn = await a.client.post(
        f"{path}/{legacy_id}/withdraw",
        headers=a.headers,
        json={
            "expected_version": 2,
            "request_key": "withdraw-legacy",
        },
    )
    assert withdrawn.status_code == 201, withdrawn.text
    with Session(a.database.engine) as seed:
        assert seed.get(KnowledgeRevision, rev_id).body == original
        assert seed.get(KnowledgeRevision, rev_id).public_source_notes == [note, private_note]
        safe = seed.get(KnowledgeRevision, UUID(withdrawn.json()["revision_id"]))
        assert "related_person_ids" not in safe.body and len(safe.public_source_notes) == 1
    result = await a.client.post(
        f"{path}/{person_id}/withdraw",
        headers=a.headers,
        json={
            "expected_version": 2,
            "request_key": "withdraw-person",
        },
    )
    assert result.status_code == 201
    view = (await a.client.get(rev_path, headers=other_ws)).json()["items"][0]
    assert view["shared_content_state"] == "filtered" and person_id not in str(view["body"])
    assert not a.chat.requests
