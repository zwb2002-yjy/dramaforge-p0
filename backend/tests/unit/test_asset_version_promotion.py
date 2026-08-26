"""P2-01 AssetVersion lifecycle promotion tests (API level)."""

from __future__ import annotations

from uuid import uuid4

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project_and_asset(client: TestClient) -> tuple[str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"promote-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Promote Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Promote Project", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    project_id = str(created.json()["id"])
    asset = client.post(
        f"/api/v1/projects/{project_id}/assets",
        json={"kind": "character", "name": "林墨", "description": "lead", "status": "active"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert asset.status_code == 201, asset.text
    return project_id, str(asset.json()["id"])


def test_create_promote_and_reject_lifecycle(client: TestClient) -> None:
    project_id, asset_id = _project_and_asset(client)
    candidate = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions",
        json={"name": "林墨·成年", "description": "v2 candidate"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert candidate.status_code == 201, candidate.text
    candidate_id = candidate.json()["id"]
    assert candidate.json()["status"] == "candidate"
    assert candidate.json()["version_number"] == 2

    promoted = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions/{candidate_id}/promote",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["status"] == "formal"

    card = client.get(f"/api/v1/projects/{project_id}/assets/{asset_id}/card")
    assert card.status_code == 200, card.text
    assert card.json()["current_version_id"] == candidate_id
    assert card.json()["current_version_status"] == "formal"

    rejected = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions",
        json={"name": "bad idea"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    rejected_id = rejected.json()["id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions/{rejected_id}/reject",
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 200
    # A rejected candidate cannot be promoted.
    rejected_promote = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions/{rejected_id}/promote",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert rejected_promote.status_code == 422, rejected_promote.text


def test_promote_keeps_only_one_formal_and_never_deletes(client: TestClient) -> None:
    project_id, asset_id = _project_and_asset(client)
    v2 = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions",
        json={"name": "v2"},
        headers={CSRF_HEADER: _csrf(client)},
    ).json()
    client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions/{v2['id']}/promote",
        headers={CSRF_HEADER: _csrf(client)},
    ).raise_for_status()
    v3 = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions",
        json={"name": "v3"},
        headers={CSRF_HEADER: _csrf(client)},
    ).json()
    client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/versions/{v3['id']}/promote",
        headers={CSRF_HEADER: _csrf(client)},
    ).raise_for_status()

    history = client.get(f"/api/v1/projects/{project_id}/assets/{asset_id}/versions").json()
    versions = [item for item in history if item["status"] in {"formal", "historical"}]
    assert sum(1 for item in versions if item["status"] == "formal") == 1
    assert any(item["id"] == v2["id"] and item["status"] == "historical" for item in history)
    assert any(item["id"] == v3["id"] and item["status"] == "formal" for item in history)
    # No version is deleted.
    assert len(history) == 3


def test_asset_version_cross_project_is_isolated(client: TestClient) -> None:
    project_id, asset_id = _project_and_asset(client)
    intruder = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"intruder-promote-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Intruder",
        },
    )
    assert intruder.status_code in {200, 201}, intruder.text
    client.headers["X-Workspace-Id"] = str(client.get("/api/v1/workspaces").json()[0]["id"])
    assert (
        client.get(f"/api/v1/projects/{project_id}/assets/{asset_id}/versions").status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/assets/{asset_id}/versions",
            json={"name": "stolen"},
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 404
    )
