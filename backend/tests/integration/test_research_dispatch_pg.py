"""Real research acceptance and worker dispatch. Only the model HTTP transport is synthetic."""

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from app.access.models import Project, User, Workspace
from app.access.project_data_policy import ProjectDataPolicy
from app.assets.project_files import ProjectFileService
from app.assets.research_models import RESEARCH_KINDS
from app.assets.source_use import SourceUseService
from app.director.invocation_models import DirectorInvocation
from app.director.research_worker import execute_research_analysis
from app.director.text_transport import DirectorTextRuntimeAdapter
from app.director.turn_models import DirectorTurn
from app.providers.model_profiles.orm import ProductionModelProfile
from app.shared.db import set_rls_context
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


@pytest.fixture
async def queued(http_agent):
    a = http_agent
    with Session(a.database.engine) as inspect:
        owner = inspect.get(Workspace, a.workspace_id).owner_user_id
    async with a.factory() as session:
        await set_rls_context(
            session, user_id=owner, workspace_id=a.workspace_id, project_id=a.project_id
        )
        session.info["selected_workspace_id"] = a.workspace_id
        actor = await session.get(User, owner)
        project = await session.get(Project, a.project_id)
        service = ProjectFileService(
            session, store=InMemoryObjectStore(), actor=actor, project_id=project.id
        )
        file = await service.upload(
            filename="合成县志.txt",
            data="青石桥每年举行灯会。".encode(),
            mime_type="text/plain",
            request_key="upload",
        )
        await service.extract(file.id)
        fragments, _ = await service.list_fragments(file.current_extraction_id, limit=1)
        await SourceUseService(session, actor=actor, project=project).declare(
            file_revision_id=file.id,
            allowed_uses=["research", "external_processing"],
            statement="合成资料，仅限隔离验收",
            request_key="initial",
        )
        await session.commit()
    base = f"/api/v1/projects/{a.project_id}/file-revisions/{file.id}"
    preview = {"source_extraction_id": str(file.current_extraction_id), "expected_file_version": 1}
    read = await a.client.post(base + "/analysis-preview", headers=a.headers, json=preview)
    assert read.status_code == 200 and read.json()["blockers"] == [], read.text
    body = {
        "preview": preview,
        "preview_fingerprint": read.json()["preview_fingerprint"],
        "request_key": str(uuid4()),
    }
    first = await a.client.post(
        base + "/analyses",
        headers=a.headers,
        json={**body, "request_key": " " + body["request_key"] + " "},
    )
    assert first.status_code == 202, first.text
    replay = await a.client.post(base + "/analyses", headers=a.headers, json=body)
    assert replay.status_code == 202 and first.json()["turn_id"] == replay.json()["turn_id"]
    assert not a.chat.requests
    return a, owner, file, fragments[0].id, UUID(first.json()["turn_id"]), body


@pytest.mark.parametrize("mode", ["normal", "invalid", "unknown", "revoked", "detached", "drift"])
async def test_queued_research_at_submission(queued, mode):
    a, owner, file, fragment, turn, decision = queued
    requests = []

    async def upstream(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "青石桥" in str(body["messages"])
        if mode == "unknown":
            raise httpx.ReadTimeout("synthetic ambiguous submission", request=request)
        data = {
            "outcomes": {
                k: {"outcome": "none", "source_fragment_ids": [str(fragment)]}
                for k in RESEARCH_KINDS
            },
            "findings": [],
        }
        content = "{" if mode == "invalid" else json.dumps(data)
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    a.chat.handle = upstream
    async with a.factory() as db:
        await set_rls_context(
            db, user_id=owner, workspace_id=a.workspace_id, project_id=a.project_id
        )
        db.info["selected_workspace_id"] = a.workspace_id
        actor = await db.get(User, owner)
        if mode in {"revoked", "drift"}:
            await SourceUseService(
                db, actor=actor, project=await db.get(Project, a.project_id)
            ).declare(
                file_revision_id=file.id,
                allowed_uses=["research", "external_processing"],
                state="revoked" if mode == "revoked" else "declared",
                statement="更新许可",
                request_key="changed",
            )
        if mode == "detached":
            await ProjectFileService(
                db, actor=actor, project_id=a.project_id, store=InMemoryObjectStore()
            ).unlink(file.file_id, expected_version=1)
        await db.commit()
    results = await asyncio.gather(
        *(execute_research_analysis(a.factory, turn_id=turn) for _ in range(2))
    )
    await execute_research_analysis(a.factory, turn_id=turn)
    path = f"/api/v1/projects/{a.project_id}/file-revisions/{file.id}/analyses"
    receipt = await a.client.post(
        path,
        headers=a.headers,
        json={**decision, "request_key": " " + decision["request_key"] + " "},
    )
    assert receipt.status_code == 202 and receipt.json()["turn_id"] == str(turn)
    changed = {**decision, "preview": {**decision["preview"], "expected_file_version": 99}}
    assert (await a.client.post(path, headers=a.headers, json=changed)).status_code == 409
    with Session(a.database.engine) as inspect:
        saved = inspect.get(DirectorTurn, turn)
        invocations = list(
            inspect.scalars(select(DirectorInvocation).where(DirectorInvocation.turn_id == turn))
        )
        if mode in {"revoked", "detached", "drift"}:
            assert not requests and not invocations and saved.status == "failed", results
        else:
            assert len(requests) == len(invocations) == 1, (results, saved.last_error)
            assert invocations[0].request_snapshot["egress_admission"]["purpose"] == "research_text"
            if mode == "normal":
                assert saved.status == "completed" and invocations[0].status == "completed", results
                assert sum(r["status"] == "published" for r in results) == 1
            else:
                expected = "failed" if mode == "invalid" else "unknown_submission"
                assert saved.status == "failed" and invocations[0].status == expected


@pytest.mark.parametrize(
    "change", ["revoke_before", "revoke_after", "egress", "model", "unlink", "reparse"]
)
async def test_changes_at_real_research_dispatch_boundary(queued, change, monkeypatch):
    a, owner, file, fragment, turn, _decision = queued
    at_boundary, proceed = asyncio.Event(), asyncio.Event()
    calls = []
    original = DirectorTextRuntimeAdapter._dispatch

    async def boundary(adapter, **kwargs):
        if change != "revoke_after":
            at_boundary.set()
            await asyncio.wait_for(proceed.wait(), 15)
        return await original(adapter, **kwargs)

    monkeypatch.setattr(DirectorTextRuntimeAdapter, "_dispatch", boundary)

    async def respond(request):
        calls.append(request)
        if change == "revoke_after":
            at_boundary.set()
            await asyncio.wait_for(proceed.wait(), 15)
        content = json.dumps(
            {
                "outcomes": {
                    k: {"outcome": "none", "source_fragment_ids": [str(fragment)]}
                    for k in RESEARCH_KINDS
                },
                "findings": [],
            }
        )
        return httpx.Response(
            200,
            json={
                "model": "mock",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
        )

    a.chat.handle = respond
    worker = asyncio.create_task(execute_research_analysis(a.factory, turn_id=turn))
    try:
        await asyncio.wait_for(at_boundary.wait(), 15)
        async with a.factory() as writer:
            await set_rls_context(
                writer, user_id=owner, workspace_id=a.workspace_id, project_id=a.project_id
            )
            writer.info["selected_workspace_id"] = a.workspace_id
            actor, project = await writer.get(User, owner), await writer.get(Project, a.project_id)
            if change == "egress":
                await ProjectDataPolicy(writer, actor=actor, project=project).put(
                    expected_revision=0,
                    mode="local_only",
                    allowed_destination_revision_ids=[],
                    allowed_purposes=[],
                )
            elif change == "model":
                profile = await writer.scalar(
                    select(ProductionModelProfile)
                    .where(ProductionModelProfile.project_id == a.project_id)
                    .with_for_update()
                )
                profile.version += 1
            elif change == "reparse":
                from app.assets.project_files import current_processor_profile

                await ProjectFileService(
                    writer, actor=actor, project_id=a.project_id, store=InMemoryObjectStore()
                ).accept_extraction(
                    file.id,
                    action="reparse",
                    request_key="reparse",
                    expected_file_version=1,
                    expected_attempt=file.attempt,
                    expected_extraction_id=file.current_extraction_id,
                    processor_profile_revision=current_processor_profile(),
                )
            elif change == "unlink":
                await ProjectFileService(
                    writer, actor=actor, project_id=a.project_id, store=InMemoryObjectStore()
                ).unlink(file.file_id, expected_version=1)
            else:
                await SourceUseService(writer, actor=actor, project=project).declare(
                    file_revision_id=file.id,
                    allowed_uses=[],
                    state="revoked",
                    statement="撤回合成资料",
                    request_key="revoke",
                )
            if change == "revoke_before":
                pid = await writer.scalar(text("select pg_backend_pid()"))
                proceed.set()
                async with asyncio.timeout(10):
                    while True:
                        with Session(a.database.engine) as inspect:
                            if inspect.scalar(
                                text(
                                    "select exists(select 1 from pg_stat_activity "
                                    "where :pid=any(pg_blocking_pids(pid)))"
                                ),
                                {"pid": pid},
                            ):
                                break
                        await asyncio.sleep(0.03)
                assert not calls
            await writer.commit()
    finally:
        proceed.set()
        result = await asyncio.wait_for(worker, 15)
    await execute_research_analysis(a.factory, turn_id=turn)
    with Session(a.database.engine) as inspect:
        records = list(
            inspect.scalars(select(DirectorInvocation).where(DirectorInvocation.turn_id == turn))
        )
    if change == "revoke_after":
        assert result["status"] == "published" and len(calls) == len(records) == 1
    else:
        assert result["status"] == "failed" and not calls and not records
