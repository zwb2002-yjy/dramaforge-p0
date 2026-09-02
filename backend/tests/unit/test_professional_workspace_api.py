"""Professional workspace asset, experiment, review, and OpenCut contracts."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project(client: TestClient) -> tuple[str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"professional-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Professional Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": workspace_id,
            "name": "Professional Project",
            "aspect_ratio": "16:9",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    return workspace_id, str(created.json()["id"])


def _shot(client: TestClient, project_id: str) -> str:
    imported = client.post(
        f"/api/v1/projects/{project_id}/scripts/import",
        json={
            "filename": "professional.md",
            "text": (
                "# Episode 1 - Demo\n\n## Scene 1 - Studio / day\nBeat.\n\n"
                "### Shot 1 - medium\nVisual: actor turns toward camera\n"
                "Dialogue: Hello\nCamera: static\n"
            ),
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code == 200, imported.text
    return str(imported.json()["shot_ids"][0])


def test_professional_assets_are_versioned(client: TestClient) -> None:
    _, project_id = _project(client)
    created = client.post(
        f"/api/v1/projects/{project_id}/assets",
        json={
            "kind": "costume",
            "name": "Black coat",
            "description": "Formal line costume",
            "metadata": {"tags": ["night", "lead"]},
            "status": "active",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    asset = created.json()
    assert asset["version"] == 1
    updated = client.patch(
        f"/api/v1/projects/{project_id}/assets/{asset['id']}",
        json={
            "expected_version": 1,
            "kind": "costume",
            "name": "Black rain coat",
            "description": "Locked official costume",
            "metadata": {"tags": ["night", "lead", "rain"]},
            "status": "active",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    versions = client.get(f"/api/v1/projects/{project_id}/assets/{asset['id']}/versions")
    assert [item["version_number"] for item in versions.json()] == [2, 1]


def test_experiment_annotation_and_opencut_manifest(client: TestClient) -> None:
    _, project_id = _project(client)
    shot_id = _shot(client, project_id)
    experiment = client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "idempotency_key": "model-b-1",
            "name": "Model B turn test",
            "source_shot_id": shot_id,
            "selected_model": "provider/model-b",
            "parameters": {"purpose": "identity_turn"},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert experiment.status_code == 201, experiment.text
    assert experiment.json()["status"] == "draft"
    assert experiment.json()["candidate_artifact_ids"] == []
    assert experiment.json()["comparison"] == {}
    decision = client.post(
        f"/api/v1/projects/{project_id}/experiments/{experiment.json()['id']}/decision",
        json={"decision": "accepted"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "accepted"

    annotation = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/annotations",
        json={
            "time_start": "1.250",
            "time_end": "2.500",
            "note": "Face drifts during the turn",
            "severity": "blocker",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert annotation.status_code == 201, annotation.text
    listed = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/annotations")
    assert listed.json()[0]["note"] == "Face drifts during the turn"

    manifest = client.get(f"/api/v1/projects/{project_id}/opencut-manifest")
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["official_line"] == "formal"
    assert manifest.json()["schema_version"] == "opencut-manifest-v2"
    assert {track["kind"] for track in manifest.json()["tracks"]} == {
        "video",
        "audio",
        "subtitle",
    }
    assert manifest.json()["shots"][0]["shot_id"] == shot_id


def test_review_rejects_ambiguous_image_coordinates(client: TestClient) -> None:
    _, project_id = _project(client)
    shot_id = _shot(client, project_id)
    response = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/annotations",
        json={
            "target_kind": "image_region",
            "x": "0.8",
            "y": "0.8",
            "width": "0.4",
            "height": "0.4",
            "note": "out of bounds",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 409, response.text
def test_professional_board_and_retired_shot_start_route_is_gone(client: TestClient) -> None:
    _, project_id = _project(client)
    shot_id = _shot(client, project_id)
    board = client.put(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/director-board",
        json={
            "mode": "rough_3d",
            "camera": {"summary": "dolly in"},
            "characters": [{"blocking": "x=.4", "pose": "walk"}],
            "scene": {"description": "studio"},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert board.status_code == 200, board.text
    assert board.json()["mode"] == "rough_3d"
    assert board.json()["version"] == 1
    board_conflict = client.put(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/director-board",
        json={
            "expected_version": 99,
            "mode": "2d",
            "camera": {},
            "characters": [],
            "scene": {},
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert board_conflict.status_code == 409, board_conflict.text
    retired_start = client.post(
        f"/api/v1/projects/{project_id}/professional/shots/{shot_id}/start",
        json={"node_keys": []},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert retired_start.status_code == 404
