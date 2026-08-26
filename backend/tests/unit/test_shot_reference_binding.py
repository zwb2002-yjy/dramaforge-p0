"""P2-05 ShotReferenceBinding CRUD + source XOR validation (API level)."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project_with_shot_and_asset(client: TestClient) -> tuple[str, str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"binding-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Binding Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Binding Project", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    project_id = str(created.json()["id"])
    imported = client.post(
        f"/api/v1/projects/{project_id}/scripts/import",
        json={
            "filename": "binding.md",
            "text": (
                "# Episode 1 - Demo\n\n## Scene 1 - Studio / day\nBeat.\n\n"
                "### Shot 1 - medium\nVisual: actor turns toward camera\n"
                "Dialogue: Hello\nCamera: static\n"
            ),
            "register_lead": False,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert imported.status_code == 200, imported.text
    shot_id = str(imported.json()["shot_ids"][0])
    asset = client.post(
        f"/api/v1/projects/{project_id}/assets",
        json={"kind": "character", "name": "林墨", "description": "", "status": "active"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert asset.status_code == 201, asset.text
    return project_id, shot_id, str(asset.json()["id"])


def test_binding_create_list_update_and_delete(client: TestClient) -> None:
    project_id, shot_id, asset_id = _project_with_shot_and_asset(client)
    created = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/references",
        json={
            "purpose": "identity",
            "asset_id": asset_id,
            "resolution_mode": "current_formal",
            "label": "@林墨",
            "stage": "both",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    binding = created.json()
    assert binding["purpose"] == "identity"
    assert binding["asset_id"] == asset_id
    assert binding["version"] == 1

    listed = client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/references")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [binding["id"]]

    updated = client.patch(
        f"/api/v1/projects/{project_id}/references/{binding['id']}",
        json={"expected_version": 1, "purpose": "clothing", "label": "黑雨衣"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["purpose"] == "clothing"
    assert updated.json()["version"] == 2

    stale = client.patch(
        f"/api/v1/projects/{project_id}/references/{binding['id']}",
        json={"expected_version": 1, "purpose": "style"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert stale.status_code == 409, stale.text

    deleted = client.delete(
        f"/api/v1/projects/{project_id}/references/{binding['id']}",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert deleted.status_code == 204, deleted.text
    assert (
        client.get(f"/api/v1/projects/{project_id}/shots/{shot_id}/references").json() == []
    )


def test_binding_requires_a_source_and_valid_purpose(client: TestClient) -> None:
    project_id, shot_id, asset_id = _project_with_shot_and_asset(client)
    no_source = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/references",
        json={"purpose": "identity", "resolution_mode": "current_formal"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert no_source.status_code == 422, no_source.text

    bad_purpose = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/references",
        json={
            "purpose": "provider_role",
            "asset_id": asset_id,
            "resolution_mode": "current_formal",
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert bad_purpose.status_code == 422, bad_purpose.text

    direct_without_artifact = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/references",
        json={"purpose": "generic_reference", "resolution_mode": "direct_artifact"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert direct_without_artifact.status_code == 422, direct_without_artifact.text
