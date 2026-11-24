"""The director consumes a public knowledge snapshot only through a current, purpose-bound pin."""

import json

import httpx
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.assets.research import CitationInput, ResearchService
from app.assets.source_use import SourceUseService
from app.shared.db import set_rls_context
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy.orm import Session
from test_director_agent_http_pg import _accept, _settle
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_pinned_knowledge_prompt_uses_only_public_body_and_stops_on_revocation(http_agent):
    a = http_agent
    with Session(a.database.engine) as seed:
        owner = seed.get(Workspace, a.workspace_id).owner_user_id
        source = Project(
            workspace_id=a.other_workspace_id, name="合成史料", aspect_ratio="16:9", budget_limit=0
        )
        seed.add(source)
        seed.flush()
        origin = source.id
        seed.commit()

    async def context(db):
        await set_rls_context(
            db, user_id=owner, workspace_id=a.other_workspace_id, project_id=origin
        )
        db.info["selected_workspace_id"] = a.other_workspace_id
        return await db.get(User, owner), await db.get(Project, origin)

    async with a.factory() as db:
        actor, project = await context(db)
        files = ProjectFileService(db, actor=actor, project_id=origin, store=InMemoryObjectStore())
        media = await files.upload(
            filename="资料.txt",
            data="绝不进入公共上下文的原句".encode(),
            mime_type="text/plain",
            request_key="file",
        )
        await files.extract(media.id)
        fragments, _ = await files.list_fragments(media.current_extraction_id, limit=1)
        private = await ResearchService(db, actor=actor, project_id=origin).create_result(
            kind="summary",
            body={"text": "项目私有研究全文"},
            verification="unverified",
            citations=[
                CitationInput(file_revision_id=media.id, source_fragment_id=fragments[0].id)
            ],
            request_key="research",
        )
        await SourceUseService(db, actor=actor, project=project).declare(
            file_revision_id=media.id,
            allowed_uses=["research", "external_processing"],
            statement="不可共享的声明",
            request_key="grant",
        )
        await db.commit()
    entry = await a.client.post(
        "/api/v1/knowledge/entries",
        headers=a.headers,
        json={
            "workspace_id": str(a.workspace_id),
            "request_key": "publish",
            "kind": "summary",
            "operation": "publish",
            "title": "合成桥志",
            "body": {"text": "已发布的知识正文"},
            "allowed_uses": ["research", "external_processing"],
            "source_links": [
                {"project_id": str(origin), "research_revision_id": str(private.revision_id)}
            ],
        },
    )
    assert entry.status_code == 201, entry.text
    e = entry.json()
    pins = f"/api/v1/projects/{a.project_id}/knowledge-references"

    async def pin(use):
        r = await a.client.post(
            pins,
            headers=a.headers,
            json={
                "knowledge_entry_id": e["entry_id"],
                "knowledge_revision_id": e["revision_id"],
                "allowed_use": use,
            },
        )
        assert r.status_code == 201, r.text
        return {
            "reference_id": r.json()["id"],
            "revision_id": e["revision_id"],
            "content_hash": e["content_hash"],
        }

    thread = (
        await a.client.post(a.threads_path, json={"scope_type": "project"}, headers=a.headers)
    ).json()
    path = f"{a.threads_path}/{thread['id']}"
    msg = {
        "content": "用这个知识解释古桥",
        "request_key": "knowledge-question",
        "knowledge_ref": await pin("research"),
    }
    denied = await a.client.post(path + "/messages", headers=a.headers, json=msg)
    assert denied.status_code == 422 and not a.chat.requests
    msg["knowledge_ref"] = await pin("external_processing")
    calls = []

    async def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        messages = payload["messages"]
        if len(calls) == 1:
            assert all(
                key not in payload for key in ("tools", "tool_choice", "parallel_tool_calls")
            )
            assert (
                messages[-1]["role"] == "tool" and messages[-1]["name"] == "read_pinned_knowledge"
            )
            assert "已发布的知识正文" in messages[-1]["content"]
            for hidden in (
                "项目私有研究全文",
                "绝不进入公共上下文的原句",
                "不可共享的声明",
                str(origin),
                str(private.revision_id),
            ):
                assert hidden not in str(messages)
        else:
            assert "已发布的知识正文" not in str(messages) and "知识派生回答" not in str(messages)
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "知识派生回答" if len(calls) == 1 else "后续回答",
                        },
                    }
                ],
            },
        )

    a.chat.handle = respond
    accepted = await _accept(a, thread["id"], msg)
    assert (await _settle(a, thread["id"], accepted))["turn"]["status"] == "completed"
    saved = (await a.client.get(path)).json()["messages"]
    assert (
        saved[0]["knowledge_ref"] == msg["knowledge_ref"] and saved[-1]["content"] == "知识派生回答"
    )
    second = await _accept(a, thread["id"], {**msg, "request_key": "again"})
    async with a.factory() as db:
        actor, project = await context(db)
        await SourceUseService(db, actor=actor, project=project).declare(
            file_revision_id=media.id,
            allowed_uses=["external_processing"],
            statement="收窄许可",
            request_key="narrow",
        )
        await db.commit()
    assert (await _settle(a, thread["id"], second))["turn"]["status"] == "stale"
    assert len(calls) == 1
    ordinary = await _accept(a, thread["id"], {"content": "换话题", "request_key": "plain"})
    assert (await _settle(a, thread["id"], ordinary))["turn"]["status"] == "completed" and len(
        calls
    ) == 2
