"""P3-03 scene structural commands (reorder/copy/split/merge with preview)."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project_with_two_scenes(client: TestClient) -> tuple[str, str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"scene-struct-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Struct Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Struct", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    project_id = str(created.json()["id"])
    imported = client.post(
        f"/api/v1/projects/{project_id}/scripts/import",
        json={
            "filename": "struct.md",
            "text": (
                "# Episode 1 - Demo\n\n"
                "## Scene 1 - Studio / day\nBeat.\n\n"
                "### Shot 1 - medium\nVisual: A turns\nDialogue: Hi\nCamera: static\n\n"
                "### Shot 2 - close_up\nVisual: A smiles\nDialogue: Bye\nCamera: locked\n\n"
                "## Scene 2 - Street / night\nBeat.\n\n"
                "### Shot 3 - wide\nVisual: B walks\nDialogue: Go\nCamera: dolly\n"
            ),
            "register_lead": False,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code == 200, imported.text
    scenes = client.get(f"/api/v1/projects/{project_id}/scenes").json()
    scenes_by_number = {item["scene_number"]: item["id"] for item in scenes}
    return (
        project_id,
        scenes_by_number[1],
        scenes_by_number[2],
    )


def test_scene_copy_duplicates_scene_and_shots(client: TestClient) -> None:
    project_id, scene_1, _ = _project_with_two_scenes(client)
    copied = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_1}/copy",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert copied.status_code == 201, copied.text
    summaries = client.get(f"/api/v1/projects/{project_id}/scenes").json()
    assert len(summaries) == 3
    copies = [item for item in summaries if "（副本）" in item["location_name"]]
    assert len(copies) == 1
    assert copies[0]["shot_count"] == 2


def test_scene_split_preview_then_split(client: TestClient) -> None:
    project_id, scene_1, _ = _project_with_two_scenes(client)
    preview = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_1}/split-preview",
        json={"at_shot_number": 2},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected"]["shot_count"] == 1

    split = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_1}/split",
        json={
            "at_shot_number": 2,
            "location_name": "Studio B",
            "time_of_day": "night",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert split.status_code == 201, split.text
    summaries = client.get(f"/api/v1/projects/{project_id}/scenes").json()
    by_name = {item["location_name"]: item for item in summaries}
    assert by_name["Studio"]["shot_count"] == 1
    assert by_name["Studio B"]["shot_count"] == 1


def test_scene_merge_preview_then_merge(client: TestClient) -> None:
    project_id, scene_1, scene_2 = _project_with_two_scenes(client)
    preview = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_1}/merge-preview",
        json={"target_scene_id": scene_2},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected"]["shot_count"] == 1

    merged = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_1}/merge",
        json={"target_scene_id": scene_2},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert merged.status_code == 200, merged.text
    summaries = client.get(f"/api/v1/projects/{project_id}/scenes").json()
    assert len(summaries) == 1
    assert summaries[0]["shot_count"] == 3


def test_scene_reorder_and_cross_project_isolation(client: TestClient) -> None:
    project_id, scene_1, scene_2 = _project_with_two_scenes(client)
    reordered = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_1}/reorder",
        json={"new_scene_number": 5},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert reordered.status_code == 200, reordered.text
    assert reordered.json()["scene_number"] == 5

    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"struct-intruder-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    )
    assert intruder.status_code in {200, 201}, intruder.text
    client.headers["X-Workspace-Id"] = str(
        client.get("/api/v1/workspaces").json()[0]["id"]
    )
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/scenes/{scene_1}/copy",
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 404
    )
