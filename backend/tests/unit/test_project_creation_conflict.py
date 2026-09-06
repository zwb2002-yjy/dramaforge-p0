"""Project creation conflict regressions."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def test_duplicate_project_name_returns_business_conflict(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"project-conflict-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Project Conflict",
        },
    )
    assert registered.status_code == 201, registered.text

    csrf = str(client.get("/api/v1/auth/csrf").json()["csrf_token"])
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    payload = {
        "workspace_id": workspace_id,
        "name": "新短剧",
        "aspect_ratio": "9:16",
        "start_type": "FREE",
        "director_autonomy": "ASSIST",
    }

    created = client.post(
        "/api/v1/projects",
        json=payload,
        headers={CSRF_HEADER: csrf},
    )
    assert created.status_code == 201, created.text

    duplicate = client.post(
        "/api/v1/projects",
        json=payload,
        headers={CSRF_HEADER: csrf},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json() == {
        "type": "https://dramaforge.local/errors/conflict",
        "title": "CONFLICT",
        "status": 409,
        "detail": "当前空间已存在同名项目，请修改项目名后重试。",
        "code": "CONFLICT",
        "details": {"code": "PROJECT_NAME_CONFLICT", "name": "新短剧"},
    }

    projects = client.get(f"/api/v1/workspaces/{workspace_id}/projects")
    assert projects.status_code == 200, projects.text
    assert [project["name"] for project in projects.json()] == ["新短剧"]
