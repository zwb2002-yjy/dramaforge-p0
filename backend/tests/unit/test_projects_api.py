"""Personal workspace project API tests."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "display_name": email.partition("@")[0]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _default_workspace_id(client: TestClient) -> str:
    response = client.get("/api/v1/workspaces")
    assert response.status_code == 200
    return str(response.json()[0]["id"])


def _select_workspace(client: TestClient, workspace_id: str) -> None:
    client.headers["X-Workspace-Id"] = workspace_id


def test_create_get_and_list_project_for_workspace_owner(client: TestClient) -> None:
    _register(client, "pm@example.com")
    workspace_id = _default_workspace_id(client)
    _select_workspace(client, workspace_id)
    project = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "ShowAlpha",
            "aspect_ratio": "9:16",
            "budget_limit": "100.50",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project.status_code == 201, project.text
    body = project.json()
    assert body["workspace_id"] == workspace_id
    assert body["stage"] == "draft"
    assert client.get(f"/api/v1/projects/{body['id']}").status_code == 200
    listed = client.get(f"/api/v1/workspaces/{workspace_id}/projects")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_other_user_cannot_read_project_or_list_owner_workspace(client: TestClient) -> None:
    _register(client, "owner2@example.com")
    workspace_id = _default_workspace_id(client)
    _select_workspace(client, workspace_id)
    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Secret", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201
    _register(client, "intruder@example.com")
    _select_workspace(client, _default_workspace_id(client))
    assert client.get(f"/api/v1/projects/{created.json()['id']}").status_code == 404
    assert client.get(f"/api/v1/workspaces/{workspace_id}/projects").status_code == 404


def test_workspace_with_project_cannot_be_deleted(client: TestClient) -> None:
    _register(client, "delete-owner@example.com")
    workspace_id = _default_workspace_id(client)
    _select_workspace(client, workspace_id)
    assert client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Retained", "aspect_ratio": "9:16"},
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 201
    deleted = client.delete(
        f"/api/v1/workspaces/{workspace_id}", headers={CSRF_HEADER: _csrf(client)}
    )
    assert deleted.status_code == 422
    assert deleted.json()["code"] == "VALIDATION_ERROR"


def test_experience_mode_switch_same_project(client: TestClient) -> None:
    _register(client, "mode@example.com")
    workspace_id = _default_workspace_id(client)
    _select_workspace(client, workspace_id)
    project = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Project", "aspect_ratio": "9:16"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    project_id = project.json()["id"]
    for mode in ("quick", "workbench"):
        response = client.put(
            f"/api/v1/projects/{project_id}/preferences/experience-mode",
            json={"experience_mode": mode},
            headers={CSRF_HEADER: _csrf(client)},
        )
        assert response.status_code == 200
        assert response.json()["experience_mode"] == mode


def test_selected_workspace_blocks_same_owner_cross_workspace_project_access(
    client: TestClient,
) -> None:
    _register(client, "workspace-isolation@example.com")
    workspace_a = _default_workspace_id(client)
    workspace_b_response = client.post(
        "/api/v1/workspaces",
        json={"name": "Workspace B"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert workspace_b_response.status_code == 201
    workspace_b = str(workspace_b_response.json()["id"])

    _select_workspace(client, workspace_a)
    project_a = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_a, "name": "A", "aspect_ratio": "9:16"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project_a.status_code == 201, project_a.text

    _select_workspace(client, workspace_b)
    project_b = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_b, "name": "B", "aspect_ratio": "9:16"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert project_b.status_code == 201, project_b.text
    project_b_id = str(project_b.json()["id"])

    _select_workspace(client, workspace_a)
    listed = client.get(f"/api/v1/workspaces/{workspace_a}/projects")
    assert [project["id"] for project in listed.json()] == [project_a.json()["id"]]
    assert client.get(f"/api/v1/projects/{project_b_id}").status_code == 404
    assert client.post(
        f"/api/v1/projects/{project_b_id}/brief",
        json={"logline": "must not update", "tone": "", "audience": ""},
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 404
    assert client.post(
        f"/api/v1/projects/{project_b_id}/dispatch",
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 404
    assert client.post(
        f"/api/v1/projects/{project_b_id}/exports/{uuid4()}/download-grant",
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 404

    _select_workspace(client, workspace_b)
    assert client.get(f"/api/v1/projects/{project_b_id}").status_code == 200
