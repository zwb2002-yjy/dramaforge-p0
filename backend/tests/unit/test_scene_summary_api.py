"""P3-01 scene summary API tests."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project_with_scenes(client: TestClient) -> tuple[str, list[str]]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"scene-summary-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Scene Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "Scene Project",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    project_id = str(created.json()["id"])
    imported = client.post(
        f"/api/v1/projects/{project_id}/scripts/import",
        json={
            "filename": "scenes.md",
            "text": (
                "# Episode 1 - Demo\n\n"
                "## Scene 1 - Studio / day\nBeat.\n\n"
                "### Shot 1 - medium\nVisual: A turns\nDialogue: Hi\nCamera: static\n\n"
                "### Shot 2 - close_up\nVisual: A smiles\nDialogue: Bye\nCamera: locked\n\n"
                "## Scene 2 - Street / night\nBeat.\n\n"
                "### Shot 3 - wide\nVisual: B walks\nDialogue: Let's go\nCamera: dolly\n"
            ),
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code == 200, imported.text
    scenes = client.get(f"/api/v1/projects/{project_id}/scenes")
    assert scenes.status_code == 200, scenes.text
    return project_id, [str(item["id"]) for item in scenes.json()]


def test_scene_summary_returns_batch_counts(client: TestClient) -> None:
    project_id, _ = _project_with_scenes(client)
    summaries = client.get(f"/api/v1/projects/{project_id}/scenes").json()
    assert len(summaries) == 2
    by_number = {item["scene_number"]: item for item in summaries}
    assert by_number[1]["location_name"] == "Studio"
    assert by_number[1]["time_of_day"] == "day"
    assert by_number[1]["shot_count"] == 2
    assert by_number[1]["formal_keyframe_count"] == 0
    assert by_number[1]["formal_video_count"] == 0
    assert by_number[1]["risk_count"] == 0
    assert by_number[1]["representative_artifact"] is None
    assert by_number[2]["shot_count"] == 1


def test_scene_summary_is_project_scoped(client: TestClient) -> None:
    project_id, _ = _project_with_scenes(client)
    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"scene-intruder-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    )
    assert intruder.status_code in {200, 201}, intruder.text
    client.headers["X-Workspace-Id"] = str(
        client.get("/api/v1/workspaces").json()[0]["id"]
    )
    assert client.get(f"/api/v1/projects/{project_id}/scenes").status_code == 404
