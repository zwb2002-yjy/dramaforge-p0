"""R4a typed DirectorTurn read/list/stop HTTP surface."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.config import clear_settings_cache, get_settings
from app.director.turn_models import DirectorTurn
from app.main import create_app
from app.shared.base import Base
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def api() -> Iterator[tuple[TestClient, Any]]:
    clear_settings_cache()
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = create_app(get_settings())
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _register(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"turn-api-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Turn API owner",
        },
    )
    assert response.status_code in {200, 201}, response.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    return workspace_id


def _project(client: TestClient, workspace_id: str, name: str) -> str:
    response = client.post(
        "/api/v1/projects",
        headers={CSRF_HEADER: _csrf(client)},
        json={"name": name, "aspect_ratio": "9:16", "workspace_id": workspace_id},
    )
    assert response.status_code in {200, 201}, response.text
    return str(response.json()["id"])


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _seed_turn(factory: Any, *, workspace_id: str, project_id: str) -> DirectorTurn:
    async def seed() -> DirectorTurn:
        from app.access.models import Workspace

        async with factory() as session:
            workspace = await session.get(Workspace, UUID(workspace_id))
            assert workspace is not None
            turn = DirectorTurn(
                workspace_id=workspace.id,
                project_id=UUID(project_id),
                actor_id=workspace.owner_user_id,
                scope_type="shot",
                scope_entity_id=uuid4(),
                request_key=f"turn-api:{uuid4().hex}",
                context_hash="a" * 64,
                input_versions={"shot": 3},
                intent_snapshot={"goal": "inspect"},
                model_resolution={"model_id": "controlled-model"},
                transport_status="succeeded",
                output_hash="b" * 64,
                output_snapshot={"summary": "safe result"},
                status="awaiting_user",
                wait_reason="proposal_decision",
                proposal_id=None,
                dispatched_command_key="command:existing",
                node_run_ids=[str(uuid4())],
                step_count=1,
            )
            session.add(turn)
            await session.commit()
            await session.refresh(turn)
            session.expunge(turn)
            return turn

    return _run(seed())


def test_turn_read_list_stop_are_scoped_typed_and_revision_checked(
    api: tuple[TestClient, Any],
) -> None:
    client, factory = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Turn project")
    other_project_id = _project(client, workspace_id, "Other project")
    turn = _seed_turn(factory, workspace_id=workspace_id, project_id=project_id)

    listed = client.get(f"/api/v1/projects/{project_id}/director/turns")
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [str(turn.id)]
    assert listed.json()[0]["model_resolution"]["model_id"] == "controlled-model"
    assert listed.json()[0]["node_run_ids"] == turn.node_run_ids

    read = client.get(f"/api/v1/projects/{project_id}/director/turns/{turn.id}")
    assert read.status_code == 200
    assert read.json()["status"] == "awaiting_user"
    assert read.json()["output_snapshot"] == {"summary": "safe result"}
    cross_project = client.get(
        f"/api/v1/projects/{other_project_id}/director/turns/{turn.id}"
    )
    assert cross_project.status_code == 404

    stop_url = f"/api/v1/projects/{project_id}/director/turns/{turn.id}/stop"
    no_csrf = client.post(stop_url, json={"expected_revision": turn.revision})
    assert no_csrf.status_code == 403
    stopped = client.post(
        stop_url,
        headers={CSRF_HEADER: _csrf(client)},
        json={"expected_revision": turn.revision},
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "cancelled"
    assert stopped.json()["wait_reason"] == "user_stopped"
    assert stopped.json()["dispatched_command_key"] == "command:existing"

    stale_revision = client.post(
        stop_url,
        headers={CSRF_HEADER: _csrf(client)},
        json={"expected_revision": turn.revision},
    )
    assert stale_revision.status_code == 409
    assert stale_revision.json()["details"]["code"] == "DIRECTOR_TURN_REVISION_CONFLICT"
    extra_field = client.post(
        stop_url,
        headers={CSRF_HEADER: _csrf(client)},
        json={"expected_revision": stopped.json()["revision"], "execute": True},
    )
    assert extra_field.status_code == 422


def test_turn_resume_is_idempotent_and_reads_current_checkpoint(
    api: tuple[TestClient, Any],
) -> None:
    client, factory = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Resume project")
    other_project_id = _project(client, workspace_id, "Resume other")
    turn = _seed_turn(factory, workspace_id=workspace_id, project_id=project_id)
    url = f"/api/v1/projects/{project_id}/director/turns/{turn.id}/resume"
    body = {"expected_revision": turn.revision, "event_key": "resume:one"}

    response = client.post(url, headers={CSRF_HEADER: _csrf(client)}, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["action"] == "review_suggestion"
    assert result["requires_confirmation"] is True
    assert result["step_count"] == turn.step_count + 1

    duplicate = client.post(url, headers={CSRF_HEADER: _csrf(client)}, json=body)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == result
    same_facts = client.post(
        url,
        headers={CSRF_HEADER: _csrf(client)},
        json={"expected_revision": turn.revision, "event_key": "resume:new-key"},
    )
    assert same_facts.status_code == 200, same_facts.text
    assert same_facts.json() == result
    cross = client.post(
        f"/api/v1/projects/{other_project_id}/director/turns/{turn.id}/resume",
        headers={CSRF_HEADER: _csrf(client)},
        json=body,
    )
    assert cross.status_code == 404


def test_resume_limit_failure_is_persisted_across_requests(api: tuple[TestClient, Any]) -> None:
    from app.director.turn_models import DirectorTurn

    client, factory = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Bounded resume")
    turn = _seed_turn(factory, workspace_id=workspace_id, project_id=project_id)

    async def exhaust() -> None:
        async with factory() as session:
            row = await session.get(DirectorTurn, turn.id)
            row.step_count = 4
            await session.commit()

    _run(exhaust())
    url = f"/api/v1/projects/{project_id}/director/turns/{turn.id}"
    response = client.post(
        f"{url}/resume", headers={CSRF_HEADER: _csrf(client)},
        json={"expected_revision": turn.revision, "event_key": "limit"},
    )
    assert response.status_code == 409, response.text
    read = client.get(url)
    assert read.status_code == 200
    assert read.json()["status"] == "failed"
    assert read.json()["wait_reason"] == "step_limit_reached"


def test_user_rejection_api_is_scoped_strict_and_persists_across_requests(api):
    client, factory = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Decision")
    other_id = _project(client, workspace_id, "Other decision")
    turn = _seed_turn(factory, workspace_id=workspace_id, project_id=project_id)

    async def prepare():
        async with factory() as session:
            row = await session.get(DirectorTurn, turn.id)
            row.request_summary = {"task": "shot_director_suggestion", "max_steps": 4}
            row.output_snapshot = {"suggested_director_state": {}}
            row.node_run_ids = []
            row.dispatched_command_key = None
            await session.commit()

    _run(prepare())
    url = f"/api/v1/projects/{project_id}/director/turns/{turn.id}/decision"
    body = {"expected_revision": turn.revision, "decision": "reject"}
    assert client.post(url, json=body).status_code == 403
    assert client.post(url.replace(project_id, other_id), json=body,
                       headers={CSRF_HEADER: _csrf(client)}).status_code == 404
    assert client.post(url, json={**body, "execute": True},
                       headers={CSRF_HEADER: _csrf(client)}).status_code == 422
    assert client.post(url, json={**body, "accepted_operation_indices": [True]},
                       headers={CSRF_HEADER: _csrf(client)}).status_code == 422
    response = client.post(url, json=body, headers={CSRF_HEADER: _csrf(client)})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    duplicate = client.post(url, json=body, headers={CSRF_HEADER: _csrf(client)})
    assert duplicate.json() == response.json()
    read = client.get(url.removesuffix("/decision"))
    assert read.json()["response_summary"]["user_decision"]["decision"] == "reject"


def test_autonomy_change_invalidates_coordination_but_preserves_submitted_links(api):
    client, factory = api
    workspace_id = _register(client)
    project_id = _project(client, workspace_id, "Autonomy intervention")
    active = _seed_turn(factory, workspace_id=workspace_id, project_id=project_id)
    profile = client.get(f"/api/v1/projects/{project_id}").json()["creative_profile"]
    response = client.patch(
        f"/api/v1/projects/{project_id}/creative-profile",
        headers={CSRF_HEADER: _csrf(client)},
        json={"expected_version": profile["version"], "director_autonomy": "MANUAL"},
    )
    assert response.status_code == 200, response.text
    read = client.get(f"/api/v1/projects/{project_id}/director/turns/{active.id}").json()
    assert read["status"] == "stale"
    assert read["wait_reason"] == "autonomy_changed"
    assert read["node_run_ids"] == active.node_run_ids
    assert read["dispatched_command_key"] == active.dispatched_command_key
