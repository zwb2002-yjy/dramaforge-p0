"""A project research discussion crosses the model boundary only under its own current grant."""

import json

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.assets.project_files import ProjectFileService
from app.assets.research import CitationInput, ResearchService
from app.assets.research_models import ResearchResultRevision
from app.assets.source_use import SourceUseService
from app.shared.db import set_rls_context
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy.orm import Session
from test_director_agent_http_pg import _accept, _settle
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


@pytest.mark.parametrize("change", ["none", "revoke", "new_revision", "unlink"])
async def test_discussion_requires_the_exact_current_research_and_eligible_sources(
    http_agent, change
):
    a = http_agent
    with Session(a.database.engine) as view:
        owner = view.get(Workspace, a.workspace_id).owner_user_id

    async def context(db):
        await set_rls_context(
            db, user_id=owner, workspace_id=a.workspace_id, project_id=a.project_id
        )
        db.info["selected_workspace_id"] = a.workspace_id
        actor = await db.get(User, owner)
        return actor, await db.get(Project, a.project_id)

    store = InMemoryObjectStore()
    async with a.factory() as db:
        actor, project = await context(db)
        files = ProjectFileService(db, actor=actor, project_id=project.id, store=store)
        f = await files.upload(
            filename="合成.txt",
            data="这句不可外传的测试原文".encode(),
            mime_type="text/plain",
            request_key="file",
        )
        await files.extract(f.id)
        fragments, _ = await files.list_fragments(f.current_extraction_id, limit=1)
        receipt = await ResearchService(db, actor=actor, project_id=project.id).create_result(
            kind="summary",
            body={"text": "研究结论是岩桥"},
            verification="unverified",
            citations=[CitationInput(file_revision_id=f.id, source_fragment_id=fragments[0].id)],
            request_key="research",
        )
        rev = await db.get(ResearchResultRevision, receipt.revision_id)
        ref = {
            "result_id": str(receipt.result_id),
            "revision_id": str(rev.id),
            "content_hash": rev.content_hash,
        }
        await db.commit()
    thread = (
        await a.client.post(a.threads_path, headers=a.headers, json={"scope_type": "project"})
    ).json()
    msg = {"content": "解释所选研究", "research_ref": ref, "request_key": "research-discussion"}
    path = f"{a.threads_path}/{thread['id']}"
    denied = await a.client.post(path + "/messages", headers=a.headers, json=msg)
    assert denied.status_code == 422 and not a.chat.requests
    async with a.factory() as db:
        actor, project = await context(db)
        await SourceUseService(db, actor=actor, project=project).declare(
            file_revision_id=f.id,
            allowed_uses=["research", "external_processing"],
            statement="合成",
            request_key="grant",
        )
        await db.commit()
    acc = await _accept(a, thread["id"], msg)
    calls = []

    async def upstream(request):
        payload = json.loads(request.content)
        calls.append(payload)
        messages = payload["messages"]
        if len(calls) == 1:
            assert messages[-1]["role"] == "tool" and "研究结论是岩桥" in messages[-1]["content"]
            assert "这句不可外传的测试原文" not in str(messages)
        else:
            assert "研究结论是岩桥" not in str(messages) and "研究答复专属" not in str(messages)
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
                            "content": "研究答复专属" if len(calls) == 1 else "普通答复",
                        },
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    a.chat.handle = upstream
    if change != "none":
        async with a.factory() as db:
            actor, project = await context(db)
            if change == "revoke":
                await SourceUseService(db, actor=actor, project=project).declare(
                    file_revision_id=f.id,
                    allowed_uses=[],
                    statement="撤回",
                    state="revoked",
                    request_key="revoke",
                )
            if change == "new_revision":
                await ResearchService(db, actor=actor, project_id=project.id).append_revision(
                    receipt.result_id,
                    expected_version=2,
                    base_revision_id=receipt.revision_id,
                    body={"text": "新判断"},
                    verification="user_asserted",
                    citations=[],
                    request_key="edit",
                )
            if change == "unlink":
                await ProjectFileService(
                    db, actor=actor, project_id=project.id, store=store
                ).unlink(f.file_id, expected_version=1)
            await db.commit()
    state = await _settle(a, thread["id"], acc)
    if change != "none":
        assert state["turn"]["status"] == "stale" and calls == [], state
        return
    assert state["turn"]["status"] == "completed", state
    assert len(calls) == 1
    again = await _accept(a, thread["id"], msg, expected_status=200)
    assert again["turn_id"] == acc["turn_id"]
    saved = (await a.client.get(path)).json()["messages"]
    assert saved[0]["research_ref"] == ref and saved[-1]["content"] == "研究答复专属"
    other = await _accept(a, thread["id"], {"content": "切换普通话题", "request_key": "regular"})
    assert (await _settle(a, thread["id"], other))["turn"]["status"] == "completed"
    assert len(calls) == 2
