"""Director projects cannot create paid work through legacy API surfaces."""

from __future__ import annotations

import asyncio

from app.events.models import OutboxEvent
from app.execution.models import NodeRun, ProviderOperation
from app.shared.db import get_session
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _director_project(client: TestClient) -> tuple[str, str]:
    assert client.post(
        "/api/v1/auth/register",
        json={
            "email": "legacy-gate@example.com",
            "password": "password123",
            "display_name": "Creator",
        },
    ).status_code == 201
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    project = client.post(
        "/api/v1/creation/start-project",
        json={
            "workspace_id": workspace_id,
            "name": "Controlled film",
            "aspect_ratio": "9:16",
            "idea": "A fictional farewell",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    project_id = str(project.json()["project_id"])
    creation = client.get(f"/api/v1/projects/{project_id}/creation-state").json()
    brief_revision_id = str(creation["brief"]["id"])
    confirmed = client.post(
        f"/api/v1/projects/{project_id}/brief/{brief_revision_id}/confirm",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert confirmed.status_code == 200, confirmed.text
    started = client.post(
        f"/api/v1/projects/{project_id}/director/workflow",
        json={},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert started.status_code == 201, started.text
    return project_id, brief_revision_id


def _counts(client: TestClient) -> tuple[int, int, int]:
    async def read() -> tuple[int, int, int]:
        override = client.app.dependency_overrides[get_session]
        iterator = override()
        session = await anext(iterator)
        try:
            return (
                int(await session.scalar(select(func.count(NodeRun.id))) or 0),
                int(await session.scalar(select(func.count(ProviderOperation.id))) or 0),
                int(await session.scalar(select(func.count(OutboxEvent.id))) or 0),
            )
        finally:
            await iterator.aclose()

    return asyncio.get_event_loop().run_until_complete(read())


def _assert_blocked(response: object) -> None:
    assert hasattr(response, "status_code")
    assert response.status_code == 422
    assert response.json()["details"]["code"] == "DIRECTOR_COMMAND_REQUIRED"


def test_director_blocks_legacy_paid_routes_without_side_effects(
    client: TestClient,
) -> None:
    project_id, brief_revision_id = _director_project(client)
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={
            "brief_revision_id": brief_revision_id,
            "plan": {"prompt": "legacy keyframe"},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert plan.status_code == 200, plan.text
    imported = client.post(
        f"/api/v1/projects/{project_id}/scripts/import",
        json={
            "filename": "legacy.md",
            "register_lead": False,
            "text": (
                "# Episode 1 - Gate\n\nLead: Lin\n\n"
                "## Scene 1 - Room / night\nA farewell.\n\n"
                "### Shot 1 - medium\nVisual: Lin waits at the door\n"
                "Dialogue: Goodbye\nCamera: static\n"
            ),
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code == 200, imported.text
    shot_id = str(imported.json()["shot_ids"][0])
    baseline = _counts(client)

    for suffix, body in (
        ("start", {}),
        ("rerun", {"changed_node_key": "subtitle"}),
    ):
        response = client.post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/{suffix}",
            json=body,
            headers={CSRF_HEADER: _csrf(client)},
        )
        _assert_blocked(response)
        assert _counts(client) == baseline

    confirm = client.post(
        f"/api/v1/projects/{project_id}/plans/{plan.json()['id']}/confirm",
        json={"materialization_ops": ["create_shot_stub", "enqueue_keyframe"]},
        headers={CSRF_HEADER: _csrf(client)},
    )
    _assert_blocked(confirm)
    assert _counts(client) == baseline

    direct = client.post(
        f"/api/v1/projects/{project_id}/generations",
        json={
            "capability": "image.generate",
            "input": {"prompt": "bypass"},
        },
        headers={"Idempotency-Key": "director-direct-media"},
    )
    _assert_blocked(direct)
    assert _counts(client) == baseline

    golden = client.post(
        f"/api/v1/projects/{project_id}/produce-golden",
        headers={CSRF_HEADER: _csrf(client)},
    )
    _assert_blocked(golden)
    assert _counts(client) == baseline

    canonical = client.post(
        f"/api/v1/projects/{project_id}/characters/lead",
        json={"name": "Fictional lead"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    _assert_blocked(canonical)
    assert _counts(client) == baseline

    for suffix in ("approve", "reject", "lock"):
        response = client.post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/{suffix}",
            json={"note": "legacy review", "reason": "legacy review", "locked": True},
            headers={CSRF_HEADER: _csrf(client)},
        )
        _assert_blocked(response)
        assert _counts(client) == baseline

    exported = client.post(
        f"/api/v1/projects/{project_id}/exports",
        headers={CSRF_HEADER: _csrf(client)},
    )
    _assert_blocked(exported)
    assert _counts(client) == baseline
