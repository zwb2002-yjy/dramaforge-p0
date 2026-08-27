"""WF1 — Canonical Professional Path closure architecture gates.

A new professional (WORKBENCH) project must not be able to reach the legacy
``confirm_plan`` materialization path (G-WF-01: legacy execution call count = 0).
A historical QUICK project remains recoverable through the same legacy route.
"""

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


def _new_project(client: TestClient, *, mode: str = "workbench") -> str:
    assert client.post(
        "/api/v1/auth/register",
        json={
            "email": f"wf1-{mode}-{id(client)}@example.com",
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
            "name": f"WF1 {mode} project",
            "aspect_ratio": "9:16",
            "experience_mode": mode,
            "idea": "canonical path check",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    return str(project.json()["project_id"])


def _create_plan(client: TestClient, project_id: str) -> str:
    creation = client.get(f"/api/v1/projects/{project_id}/creation-state").json()
    brief_revision_id = str(creation["brief"]["id"])
    confirmed = client.post(
        f"/api/v1/projects/{project_id}/brief/{brief_revision_id}/confirm",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert confirmed.status_code == 200, confirmed.text
    plan = client.post(
        f"/api/v1/projects/{project_id}/plans",
        json={
            "brief_revision_id": brief_revision_id,
            "plan": {"prompt": "legacy keyframe"},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert plan.status_code == 200, plan.text
    return str(plan.json()["id"])


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


def test_new_professional_project_blocks_legacy_confirm_without_side_effects(
    client: TestClient,
) -> None:
    project_id = _new_project(client, mode="workbench")
    plan_id = _create_plan(client, project_id)
    baseline = _counts(client)

    confirm = client.post(
        f"/api/v1/projects/{project_id}/plans/{plan_id}/confirm",
        json={"materialization_ops": ["create_shot_stub", "enqueue_keyframe"]},
        headers={CSRF_HEADER: _csrf(client)},
    )

    assert confirm.status_code == 422
    assert confirm.json()["details"]["code"] == "PROFESSIONAL_PATH_ONLY"
    assert _counts(client) == baseline


def test_new_professional_project_defaults_to_workbench_mode(
    client: TestClient,
) -> None:
    assert client.post(
        "/api/v1/auth/register",
        json={
            "email": f"wf1-default-{id(client)}@example.com",
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
            "name": "Default mode project",
            "aspect_ratio": "9:16",
            "idea": "default mode",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    assert project.json()["experience_mode"] == "workbench"


def test_historical_quick_project_remains_recoverable_via_legacy_confirm(
    client: TestClient,
) -> None:
    project_id = _new_project(client, mode="quick")
    plan_id = _create_plan(client, project_id)

    # A QUICK (historical) project may still run the legacy confirm path.
    confirm = client.post(
        f"/api/v1/projects/{project_id}/plans/{plan_id}/confirm",
        json={"materialization_ops": ["create_shot_stub", "enqueue_keyframe"]},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["materialization_ops"]
