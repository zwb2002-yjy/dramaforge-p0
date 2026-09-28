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
    client.headers["X-Workspace-Id"] = str(client.get("/api/v1/workspaces").json()[0]["id"])
    response = client.patch(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/design",
        json={"expected_version": 1, "image_prompt": "stolen"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 404, response.text


def test_voice_options_are_project_scoped_and_do_not_probe(client: TestClient, monkeypatch) -> None:
    project_id, _shot_id = _project_with_shot(client)

    def unexpected(*args, **kwargs):
        raise AssertionError("Reading speech choices must not start a provider")

    monkeypatch.setattr("app.providers.voice_runtime.get_voice_adapter", unexpected)
    response = client.get(f"/api/v1/projects/{project_id}/voice-options")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["engine"] == "edge-tts"
    assert data["status"] == "disabled"
    assert {voice["id"] for voice in data["voices"]} == {
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-YunxiNeural",
    }
    assert "未联网验证" in data["service_notice"]
    assert client.get(f"/api/v1/projects/{uuid4()}/voice-options").status_code == 404
    del client.headers["X-Workspace-Id"]
    assert client.get(f"/api/v1/projects/{project_id}/voice-options").status_code in {400, 403, 422}


def test_saved_voice_is_validated_and_retained_without_generating(
    client: TestClient, monkeypatch
) -> None:
    project_id, shot_id = _project_with_shot(client)

    def unexpected(*args, **kwargs):
        raise AssertionError("Saving a voice is not a speech generation gate")

    monkeypatch.setattr("app.providers.voice_runtime.get_voice_adapter", unexpected)
    path = f"/api/v1/projects/{project_id}/shots/{shot_id}/design"
    response = client.patch(
        path,
        json={
            "expected_version": 1,
            "director_state": {"voice": {"voice_id": "zh-CN-YunxiNeural", "rate_percent": -10}},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["director_state"]["voice"] == {
        "voice_id": "zh-CN-YunxiNeural",
        "rate_percent": -10,
    }
    invalid = client.patch(
        path,
        json={
            "expected_version": response.json()["version"],
            "director_state": {"voice": {"voice_id": "cmn", "rate_percent": 0}},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert invalid.status_code == 422, invalid.text
    excessive = client.patch(
        path,
        json={
            "expected_version": response.json()["version"],
            "director_state": {"voice": {"rate_percent": 31}},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert excessive.status_code == 422, excessive.text
