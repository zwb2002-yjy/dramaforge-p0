"""Accepted analysis requests become one frozen queued Director Turn (I4-02)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.access.models import Project, User, Workspace
from app.api.v1 import research as research_api
from app.assets.project_files import ProjectFileService
from app.assets.source_use import SourceUseService
from app.director.research_import import ResearchImportService, ResearchRequest
from app.director.turn_models import DirectorTurn
from app.shared.errors import AppError
from app.shared.security import CSRF_HEADER
from app.storage.minio_store import InMemoryObjectStore
from test_director_turn_api import _csrf, _project, _register
from test_director_turn_api import api as api


@pytest.fixture
async def import_world(session):
    actor = User(email=f"accept-{uuid4()}@example.com", display_name="A", password_hash="x")
    session.add(actor)
    await session.flush()
    workspace = Workspace(name="Accept", owner_user_id=actor.id)
    session.add(workspace)
    await session.flush()
    project = Project(workspace_id=workspace.id, name="P", aspect_ratio="16:9", budget_limit=0)
    session.add(project)
    await session.commit()
    session.info["selected_workspace_id"] = workspace.id
    files = ProjectFileService(
        session, store=InMemoryObjectStore(), actor=actor, project_id=project.id
    )
    revision = await files.upload(
        filename="地方志.txt",
        data="古桥始建于明代。\n桥体为石拱结构。".encode(),
        mime_type="text/plain",
        request_key="accept-upload",
    )
    await files.extract(revision.id)
    fragments, _total = await files.list_fragments(revision.current_extraction_id, limit=10)
    return {
        "session": session,
        "actor": actor,
        "project": project,
        "revision": revision,
        "extraction_id": revision.current_extraction_id,
        "fragments": fragments,
        "service": ResearchImportService(session),
    }


def _request(world, *, key: str = "accept-1", fingerprint: str = "a" * 64) -> ResearchRequest:
    return ResearchRequest(
        file_revision_id=world["revision"].id,
        source_extraction_id=world["extraction_id"],
        categories=["summary", "person"],
        targets=[],
        model_identity={"model_id": "text-model-1"},
        preview_fingerprint=fingerprint,
        request_key=key,
    )


async def test_accept_creates_one_queued_research_turn(import_world):
    world = import_world
    acceptance = await world["service"].accept(
        project=world["project"], actor=world["actor"], request=_request(world)
    )
    assert acceptance.created is True and acceptance.accepted_revision == "a" * 64
    session = world["session"]
    turn = await session.get(DirectorTurn, acceptance.turn_id)
    assert turn is not None
    assert turn.scope_type == "research_analysis"
    assert turn.status == "queued"
    assert turn.input_versions["preview_fingerprint"] == "a" * 64
    assert turn.input_versions["categories"] == ["summary", "person"]
    assert turn.input_versions["fragment_ids"] == [
        str(fragment.id) for fragment in world["fragments"]
    ]
    replay = await world["service"].accept(
        project=world["project"], actor=world["actor"], request=_request(world)
    )
    assert replay.turn_id == acceptance.turn_id and replay.created is False
    with pytest.raises(AppError):
        await world["service"].accept(
            project=world["project"],
            actor=world["actor"],
            request=_request(world, fingerprint="b" * 64),
        )


class _FakeResolved:
    model_id = "text-model-1"
    resolution = {
        "model_id": "text-model-1",
        "profile_id": None,
        "profile_version": None,
        "manifest_version": "v1",
        "connection_revision_id": "conn-1",
    }


def test_http_acceptance_creates_turn_and_rejects_drift(api, monkeypatch):
    from uuid import UUID

    client, factory = api
    store = InMemoryObjectStore()
    monkeypatch.setattr("app.api.v1.project_files.get_object_store", lambda: store)
    workspace = _register(client)
    project = _project(client, workspace, "Accept")

    async def fake_resolve(session, *, project):
        return _FakeResolved()

    monkeypatch.setattr(research_api, "resolve_agent_text_model", fake_resolve)
    path = f"/api/v1/projects/{project}/files"
    uploaded = client.post(
        path,
        params={"filename": "地方志.txt", "request_key": "accept-src"},
        content="古桥始建于明代。\n桥体为石拱结构。".encode(),
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert uploaded.status_code == 201, uploaded.text
    source = uploaded.json()

    async def setup() -> tuple[str, str]:
        async with factory() as session:
            ws = await session.get(Workspace, UUID(workspace))
            assert ws is not None
            actor = await session.get(User, ws.owner_user_id)
            assert actor is not None
            session.info["selected_workspace_id"] = UUID(workspace)
            service = ProjectFileService(
                session, store=store, actor=actor, project_id=UUID(project)
            )
            await service.extract(UUID(source["revision_id"]))
            await session.commit()
            project_row = await session.get(Project, UUID(project))
            assert project_row is not None
            await SourceUseService(session, actor=actor, project=project_row).declare(
                file_revision_id=UUID(source["revision_id"]),
                allowed_uses=["research", "external_processing"],
                statement="研究用途",
                request_key="accept-su",
            )
            await session.commit()
            current = await service.read_current(UUID(source["id"]))
            return str(current[1].current_extraction_id), str(current[1].id)

    extraction_id, revision_id = asyncio.run(setup())
    preview_path = (
        f"/api/v1/projects/{project}/file-revisions/{revision_id}/analysis-preview"
    )
    preview_body = {"source_extraction_id": extraction_id, "expected_file_version": 1}
    preview = client.post(preview_path, json=preview_body).json()
    assert preview["blockers"] == [], preview["blockers"]
    analyses_path = (
        f"/api/v1/projects/{project}/file-revisions/{revision_id}/analyses"
    )
    accepted = client.post(
        analyses_path,
        json={
            "request_key": "accept-http-1",
            "preview": preview_body,
            "preview_fingerprint": preview["preview_fingerprint"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert accepted.status_code == 202, accepted.text
    payload = accepted.json()
    assert payload["master_run_id"] is None and payload["flow_instance_id"] is None
    assert payload["accepted_revision"] == preview["preview_fingerprint"]
    turn_id = payload["turn_id"]

    async def read_turn() -> tuple[str, str, str]:
        async with factory() as session:
            turn = await session.get(DirectorTurn, UUID(turn_id))
            assert turn is not None
            return turn.scope_type, turn.status, turn.request_key

    scope_type, status, request_key = asyncio.run(read_turn())
    assert scope_type == "research_analysis" and status == "queued"
    assert request_key == "accept-http-1"
    replay = client.post(
        analyses_path,
        json={
            "request_key": "accept-http-1",
            "preview": preview_body,
            "preview_fingerprint": preview["preview_fingerprint"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert replay.status_code == 202 and replay.json()["turn_id"] == turn_id
    drift = client.post(
        analyses_path,
        json={
            "request_key": "accept-http-2",
            "preview": preview_body,
            "preview_fingerprint": "0" * 64,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert drift.status_code == 409
    assert drift.json()["code"] == "RESEARCH_PREVIEW_DRIFT"


def test_http_acceptance_reports_blockers(api, monkeypatch):
    client, _factory = api
    workspace = _register(client)
    project = _project(client, workspace, "Blocked")
    # No source use declaration and no model: the preview carries blockers and the
    # acceptance refuses without creating a Turn.
    path = f"/api/v1/projects/{project}/files"
    uploaded = client.post(
        path,
        params={"filename": "blocked.txt", "request_key": "blocked-src"},
        content=b"no model",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert uploaded.status_code == 201
    preview_path = (
        f"/api/v1/projects/{project}/file-revisions/"
        f"{uploaded.json()['revision_id']}/analysis-preview"
    )
    response = client.post(
        preview_path,
        json={"source_extraction_id": str(uuid4()), "expected_file_version": 1},
    )
    assert response.status_code == 200
    blockers = response.json()["blockers"]
    assert "text_model_unavailable" in blockers
    assert "source_extraction_missing" in blockers
    analyses_path = (
        f"/api/v1/projects/{project}/file-revisions/"
        f"{uploaded.json()["revision_id"]}/analyses"
    )
    refused = client.post(
        analyses_path,
        json={
            "request_key": "blocked-accept",
            "preview": {
                "source_extraction_id": str(uuid4()),
                "expected_file_version": 1,
            },
            "preview_fingerprint": response.json()["preview_fingerprint"],
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "RESEARCH_BLOCKED"
    assert "text_model_unavailable" in refused.json()["details"]["blockers"]
