"""Isolated owner publication and consumer-project reference decisions on restricted PG."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.access.models import Project, User, Workspace
from app.assets.knowledge_models import KnowledgeEntry, KnowledgeRevision, KnowledgeSourceLink
from app.assets.project_files import ProjectFileService
from app.assets.research import CitationInput, ResearchService
from app.assets.research_analysis_models import ResearchAnalysis, ResearchAnalysisResult
from app.assets.source_use import SourceUseService
from app.shared.db import set_rls_context
from app.storage.minio_store import InMemoryObjectStore
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_director_agent_http_pg import http_agent as http_agent
from test_director_agent_http_pg import http_database as http_database
from test_director_turn_lifecycle_pg import pytestmark as pytestmark


async def test_linked_publication_and_pins_follow_each_current_source(http_agent):
    a = http_agent
    with Session(a.database.engine) as seed:
        owner = seed.get(Workspace, a.workspace_id).owner_user_id
        project = Project(
            workspace_id=a.other_workspace_id, name="私有资料", aspect_ratio="16:9", budget_limit=0
        )
        seed.add(project)
        seed.flush()
        source_project = project.id
        seed.commit()

    async def source_context(db):
        await set_rls_context(
            db, user_id=owner, workspace_id=a.other_workspace_id, project_id=source_project
        )
        db.info["selected_workspace_id"] = a.other_workspace_id
        return SourceUseService(
            db, actor=await db.get(User, owner), project=await db.get(Project, source_project)
        )

    async with a.factory() as db:
        assert await db.scalar(text("select current_user")) == "dramaforge_app"
        source_use = await source_context(db)
        actor = await db.get(User, owner)
        files = ProjectFileService(
            db, store=InMemoryObjectStore(), actor=actor, project_id=source_project
        )
        citations, originals = [], []
        for name in ("桥志", "镇志"):
            revision = await files.upload(
                filename=f"{name}.txt",
                data=f"{name}记载古桥".encode(),
                mime_type="text/plain",
                request_key=name,
            )
            await files.extract(revision.id)
            fragments, _ = await files.list_fragments(revision.current_extraction_id, limit=2)
            citations.append(
                CitationInput(
                    file_revision_id=revision.id,
                    source_fragment_id=fragments[0].id,
                    claim_key="root",
                )
            )
            originals.append(revision)
        research = ResearchService(db, actor=actor, project_id=source_project)
        base = await research.create_result(
            kind="summary",
            body={"text": "桥梁研究"},
            citations=citations,
            verification="unverified",
            request_key="base",
        )
        edit = await research.append_revision(
            base.result_id,
            expected_version=2,
            base_revision_id=base.revision_id,
            body={"text": "两本志书均记载古桥"},
            citations=[],
            verification="user_asserted",
            request_key="edit",
        )
        first_grant = await source_use.declare(
            file_revision_id=originals[0].id,
            allowed_uses=["research"],
            statement="合成测试",
            request_key="first",
        )
        await db.commit()

    path = "/api/v1/knowledge/entries"
    uses = ["research", "export", "creation"]

    def payload(**kw):
        return {
            "workspace_id": str(a.workspace_id),
            "kind": "summary",
            "title": "古桥",
            "request_key": str(uuid4()),
            "operation": "publish",
            "body": {"text": "古桥概况"},
            "allowed_uses": uses,
            "source_links": [
                {"project_id": str(source_project), "research_revision_id": str(edit.revision_id)}
            ],
            **kw,
        }

    async def create(data):
        return await a.client.post(path, headers=a.headers, json=data)

    async def permits(db, revision, *purposes):
        service = await source_context(db)
        await service.declare(
            file_revision_id=revision.id,
            allowed_uses=list(purposes),
            statement="合成资料测试",
            request_key=str(uuid4()),
            state="declared" if purposes else "revoked",
        )

    # Drafts preserve provenance. Publication requires every source, even with no intended uses.
    draft = await create(payload(operation="save_draft"))
    assert draft.status_code == 201, draft.text
    entry_id = draft.json()["entry_id"]
    revisions_path = f"{path}/{entry_id}/revisions"
    assert (await create(payload(allowed_uses=[]))).status_code == 422
    append = payload(expected_version=2, source_links=[])
    for key in ("kind", "workspace_id"):
        del append[key]

    async def publish(data):
        return await a.client.post(revisions_path, headers=a.headers, json=data)

    async with a.factory() as db:
        await permits(db, originals[1], *uses)
        await db.commit()
    denied = await publish(append)
    assert denied.status_code == 422 and "KNOWLEDGE_SOURCE_USE_RESTRICTED" in denied.text
    assert str(source_project) not in denied.text
    assert (await a.client.get(revisions_path)).json()["total"] == 1
    async with a.factory() as db:
        await permits(db, originals[0], *uses)
        await db.commit()
    published = await publish(append)
    assert published.status_code == 201, published.text
    revision_id = published.json()["revision_id"]
    with Session(a.database.engine) as inspect:
        link = inspect.scalar(
            select(KnowledgeSourceLink).where(
                KnowledgeSourceLink.knowledge_revision_id == UUID(revision_id)
            )
        )
        assert link.project_id == source_project and link.research_revision_id == edit.revision_id
    for route in (revisions_path, f"{path}/{entry_id}"):
        shared = await a.client.get(route)
        assert shared.status_code == 200 and str(edit.revision_id) not in shared.text
        assert str(source_project) not in shared.text and str(originals[0].id) not in shared.text
    pins = f"/api/v1/projects/{a.project_id}/knowledge-references"

    async def pin(use):
        return await a.client.post(
            pins,
            headers=a.headers,
            json={
                "knowledge_entry_id": entry_id,
                "knowledge_revision_id": revision_id,
                "allowed_use": use,
            },
        )

    reference = await pin("export")
    assert reference.status_code == 201 and reference.json()["availability"] == "published"
    impact = await a.client.get(
        f"/api/v1/projects/{source_project}/source-use-subjects/{first_grant.subject_id}/impact",
        headers={**a.headers, "X-Workspace-Id": str(a.other_workspace_id)},
    )
    assert impact.status_code == 200, impact.text
    assert impact.json() == {"items": [], "next_cursor": None, "other_project_uses_count": 1}
    # An in-flight grant change takes the normal writer's project lock. A concurrent new pin
    # must wait and see the committed restriction before it inserts a reference.
    async with a.factory() as writer:
        await permits(writer, originals[0], "research")
        pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        pending = asyncio.create_task(pin("creation"))
        try:
            async with asyncio.timeout(10):
                while not pending.done():
                    with Session(a.database.engine) as inspect:
                        if inspect.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                                "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                            ),
                            {"pid": pid},
                        ):
                            break
                    await asyncio.sleep(0.03)
                assert not pending.done()
            await writer.commit()
        finally:
            await writer.rollback()
            blocked = await asyncio.wait_for(pending, 10)
    assert blocked.status_code == 409, blocked.text
    assert (await a.client.get(pins)).json()["items"][0]["availability"] == "restricted"
    assert (await pin("research")).status_code == 201
    patch = f"{pins}/{reference.json()['id']}"
    assert (
        await a.client.patch(
            patch, headers=a.headers, json={"expected_version": 1, "attached": False}
        )
    ).status_code == 200
    assert (
        await a.client.patch(
            patch, headers=a.headers, json={"expected_version": 2, "attached": True}
        )
    ).status_code == 409
    async with a.factory() as db:
        await permits(db, originals[1])
        await db.commit()
    assert (await a.client.get(pins)).json()["items"][0]["availability"] == "restricted"
    assert (await publish(append)).json() == published.json()
    assert (
        await publish(
            {
                **append,
                "request_key": str(uuid4()),
                "expected_version": 3,
                "allowed_uses": ["research"],
            }
        )
    ).status_code == 422
    withdrawn = await a.client.post(
        f"{path}/{entry_id}/withdraw",
        headers=a.headers,
        json={"expected_version": 3, "request_key": "withdraw"},
    )
    assert withdrawn.status_code == 201
    with Session(a.database.engine) as inspect:
        assert (
            inspect.scalar(
                select(func.count())
                .select_from(KnowledgeSourceLink)
                .join(
                    KnowledgeRevision,
                    KnowledgeRevision.id == KnowledgeSourceLink.knowledge_revision_id,
                )
                .where(KnowledgeRevision.entry_id == UUID(entry_id))
            )
            == 3
        )
    assert not a.chat.requests


async def test_analysis_file_and_legacy_missing_link_are_checked(http_agent):
    a = http_agent
    with Session(a.database.engine) as seed:
        owner = seed.get(Workspace, a.workspace_id).owner_user_id
    store = InMemoryObjectStore()
    async with a.factory() as db:
        await set_rls_context(
            db, user_id=owner, workspace_id=a.workspace_id, project_id=a.project_id
        )
        db.info["selected_workspace_id"] = a.workspace_id
        actor = await db.get(User, owner)
        files = ProjectFileService(db, store=store, actor=actor, project_id=a.project_id)
        file = await files.upload(
            filename="城志.txt",
            data="城志".encode(),
            mime_type="text/plain",
            request_key="chronicle",
        )
        await files.extract(file.id)
        file_id = file.file_id
        uses = SourceUseService(db, actor=actor, project=await db.get(Project, a.project_id))
        await uses.declare(
            file_revision_id=file.id,
            allowed_uses=["research"],
            statement="合成",
            request_key="declare",
        )
        research = ResearchService(db, actor=actor, project_id=a.project_id)
        receipt = await research.create_result(
            kind="summary",
            body={"text": "城志研究"},
            citations=[],
            verification="unverified",
            request_key="result",
        )
        # Synthetic manifest links a result to an analysed file even with no verbatim citation.
        manifest = ResearchAnalysis(
            project_id=a.project_id,
            file_revision_id=file.id,
            source_extraction_id=file.current_extraction_id,
            coverage={"complete": True},
            category_outcomes={"summary": "findings"},
            manifest_hash="c" * 64,
            request_hash="d" * 64,
            request_key="synthetic-manifest",
            completed_at=datetime.now(UTC),
        )
        db.add(manifest)
        await db.flush()
        db.add(
            ResearchAnalysisResult(
                project_id=a.project_id,
                analysis_id=manifest.id,
                research_revision_id=receipt.revision_id,
                category="summary",
                ordinal=0,
            )
        )
        await db.commit()

    path = "/api/v1/knowledge/entries"
    create = {
        "workspace_id": str(a.workspace_id),
        "kind": "summary",
        "operation": "publish",
        "title": "城志",
        "body": {"text": "城志"},
        "allowed_uses": ["export"],
        "request_key": "export",
        "source_links": [
            {"project_id": str(a.project_id), "research_revision_id": str(receipt.revision_id)}
        ],
    }
    assert (await a.client.post(path, headers=a.headers, json=create)).status_code == 422
    valid = await a.client.post(
        path,
        headers=a.headers,
        json={**create, "request_key": "research", "allowed_uses": ["research"]},
    )
    assert valid.status_code == 201, valid.text
    entry_id = UUID(valid.json()["entry_id"])
    with Session(a.database.engine) as seed:
        entry = seed.get(KnowledgeEntry, entry_id)
        base = seed.get(KnowledgeRevision, entry.current_revision_id)
        older_writer = KnowledgeRevision(
            owner_user_id=owner,
            entry_id=entry_id,
            number=2,
            title=base.title,
            body=base.body,
            content_hash=base.content_hash,
            allowed_uses=["research", "export"],
            public_source_notes=[],
            operation="publish",
            publication_status="published",
            expected_entry_version=2,
            result_entry_version=3,
            request_key="legacy",
            request_hash="a" * 64,
        )
        seed.add(older_writer)
        seed.flush()
        historical_id = str(older_writer.id)
        entry.current_revision_id = older_writer.id
        entry.version = 3
        seed.commit()
    pins = f"/api/v1/projects/{a.project_id}/knowledge-references"
    pin = {
        "knowledge_entry_id": str(entry_id),
        "knowledge_revision_id": historical_id,
        "allowed_use": "export",
    }
    assert (await a.client.post(pins, headers=a.headers, json=pin)).status_code == 409
    assert (
        await a.client.post(pins, headers=a.headers, json={**pin, "allowed_use": "research"})
    ).status_code == 201
    async with a.factory() as db:
        await set_rls_context(
            db, user_id=owner, workspace_id=a.workspace_id, project_id=a.project_id
        )
        db.info["selected_workspace_id"] = a.workspace_id
        files = ProjectFileService(
            db, store=store, actor=await db.get(User, owner), project_id=a.project_id
        )
        await files.unlink(file_id, expected_version=1)
        await db.commit()
    assert (await a.client.get(pins)).json()["items"][0]["availability"] == "restricted"
    assert not a.chat.requests
