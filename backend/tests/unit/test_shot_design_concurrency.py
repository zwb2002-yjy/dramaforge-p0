"""P1-03 shot design PATCH optimistic concurrency tests."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project_with_shot(client: TestClient) -> tuple[str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"shot-design-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Shot Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "Design Project",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    project_id = str(created.json()["id"])
    imported = client.post(
        f"/api/v1/projects/{project_id}/scripts/import",
        json={
            "filename": "design.md",
            "text": (
                "# Episode 1 - Demo\n\n## Scene 1 - Studio / day\nBeat.\n\n"
                "### Shot 1 - medium\nVisual: actor turns toward camera\n"
                "Dialogue: Hello\nCamera: static\n"
            ),
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code == 200, imported.text
    return project_id, str(imported.json()["shot_ids"][0])


def test_shot_design_patch_writes_director_state_and_prompts(client: TestClient) -> None:
    project_id, shot_id = _project_with_shot(client)
    response = client.patch(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/design",
        json={
            "expected_version": 1,
            "director_state": {
                "framing": {"shot_size": "close_up", "angle": "eye_level"},
                "camera": {"movement": "locked", "focal_length_mm": 50},
                "action": {"description": "缓慢回头看向门口"},
            },
            "image_prompt": "close up, eye level, slow turn",
            "video_prompt": "locked camera, slow turn",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == 2
    assert body["director_state"]["framing"] == {
        "shot_size": "close_up",
        "angle": "eye_level",
    }
    assert body["director_state"]["camera"] == {"movement": "locked", "focal_length_mm": 50}
    assert body["image_prompt"] == "close up, eye level, slow turn"
    assert body["video_prompt"] == "locked camera, slow turn"


def test_shot_design_patch_stale_version_returns_409(client: TestClient) -> None:
    project_id, shot_id = _project_with_shot(client)
    first = client.patch(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/design",
        json={
            "expected_version": 1,
            "director_state": {"action": {"description": "第一次修改"}},
            "image_prompt": "version one",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2

    stale = client.patch(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/design",
        json={
            "expected_version": 1,
            "image_prompt": "stale writer must lose",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "CONFLICT"
    assert stale.json()["details"]["actual_version"] == 2


def test_shot_design_patch_requires_project_ownership(client: TestClient) -> None:
    project_id, shot_id = _project_with_shot(client)
    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"shot-intruder-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    )
    assert intruder.status_code in {200, 201}, intruder.text
    client.headers["X-Workspace-Id"] = str(
        client.get("/api/v1/workspaces").json()[0]["id"]
    )
    response = client.patch(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/design",
        json={"expected_version": 1, "image_prompt": "stolen"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 404, response.text
