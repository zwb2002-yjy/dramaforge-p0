"""P1-01 workspace state API tests."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project(client: TestClient) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"workspace-state-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Workspace Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "State Project",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    return str(created.json()["id"])


def test_workspace_state_defaults_empty_and_round_trips(client: TestClient) -> None:
    project_id = _project(client)
    initial = client.get(f"/api/v1/projects/{project_id}/workspace-state")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {"state": {}}

    updated = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={
            "state": {
                "last_view": "scenes",
                "selected_scene_id": None,
                "panels": {"inspector": True},
            }
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["state"]["last_view"] == "scenes"
    assert updated.json()["state"]["panels"] == {"inspector": True}

    reread = client.get(f"/api/v1/projects/{project_id}/workspace-state")
    assert reread.status_code == 200, reread.text
    assert reread.json() == updated.json()


def test_workspace_state_patch_merges_partial(client: TestClient) -> None:
    project_id = _project(client)
    first = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"last_view": "assets"}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert first.status_code == 200, first.text
    merged = client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"selected_shot_id": "abc"}},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["state"] == {"last_view": "assets", "selected_shot_id": "abc"}


def test_workspace_state_is_scoped_to_the_owning_user(client: TestClient) -> None:
    project_id = _project(client)
    client.patch(
        f"/api/v1/projects/{project_id}/workspace-state",
        json={"state": {"last_view": "edit"}},
        headers={CSRF_HEADER: _csrf(client)},
    ).raise_for_status()

    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"intruder-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    )
    assert intruder.status_code in {200, 201}, intruder.text
    client.headers["X-Workspace-Id"] = str(
        client.get("/api/v1/workspaces").json()[0]["id"]
    )
    assert (
        client.get(f"/api/v1/projects/{project_id}/workspace-state").status_code == 404
    )
    assert (
        client.patch(
            f"/api/v1/projects/{project_id}/workspace-state",
            json={"state": {"last_view": "edit"}},
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 404
    )
