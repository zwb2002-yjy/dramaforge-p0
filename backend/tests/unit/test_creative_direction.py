"""Project creative direction: explicit note with profile-version CAS (I7)."""

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
            "email": f"direction-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Direction Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "work_type": "serial_comic",
            "workspace_id": workspace_id,
            "name": "Direction Project",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    return str(created.json()["id"])


def test_direction_starts_empty_and_saves_with_cas(client: TestClient) -> None:
    project_id = _project(client)
    read = client.get(f"/api/v1/projects/{project_id}/creative-direction")
    assert read.status_code == 200, read.text
    assert read.json() == {"profile_version": 1, "direction": ""}

    saved = client.post(
        f"/api/v1/projects/{project_id}/creative-direction",
        json={
            "expected_profile_version": 1,
            "direction": "  明代江南，克制含蓄，避免奇观化。  ",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "profile_version": 2,
        "direction": "明代江南，克制含蓄，避免奇观化。",
    }
    reread = client.get(f"/api/v1/projects/{project_id}/creative-direction")
    assert reread.json()["direction"] == "明代江南，克制含蓄，避免奇观化。"

    stale = client.post(
        f"/api/v1/projects/{project_id}/creative-direction",
        json={"expected_profile_version": 1, "direction": "另一个方向"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["details"]["code"] == "CREATIVE_PROFILE_VERSION_CONFLICT"

    blank = client.post(
        f"/api/v1/projects/{project_id}/creative-direction",
        json={"expected_profile_version": 2, "direction": ""},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert blank.status_code == 422
