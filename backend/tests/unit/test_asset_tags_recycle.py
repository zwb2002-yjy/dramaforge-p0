"""P2-03 AssetTag / recycle API tests."""

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
            "email": f"tags-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Tag Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Tag Project", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    return str(created.json()["id"])


def _asset(client: TestClient, project_id: str, name: str, kind: str = "character") -> str:
    created = client.post(
        f"/api/v1/projects/{project_id}/assets",
        json={"kind": kind, "name": name, "description": "", "status": "active"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_tag_create_set_and_filter(client: TestClient) -> None:
    project_id = _project(client)
    tag = client.post(
        f"/api/v1/projects/{project_id}/asset-tags",
        json={"name": "  Lead  "},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert tag.status_code == 201, tag.text
    assert tag.json()["normalized_name"] == "lead"

    asset_id = _asset(client, project_id, "林墨")
    updated = client.put(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/tags",
        json={"tags": ["Lead", "Night", "雨夜"]},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert updated.status_code == 200, updated.text
    names = {item["normalized_name"] for item in updated.json()}
    assert names == {"lead", "night", "雨夜"}

    filtered = client.get(f"/api/v1/projects/{project_id}/assets", params={"tags": "lead"})
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()] == [asset_id]

    listed = client.get(f"/api/v1/projects/{project_id}/asset-tags")
    assert {item["normalized_name"] for item in listed.json()} == {"lead", "night", "雨夜"}


def test_asset_list_filters_kind_status_and_name(client: TestClient) -> None:
    project_id = _project(client)
    character_id = _asset(client, project_id, "林墨", kind="character")
    _asset(client, project_id, "雨衣", kind="costume")

    by_kind = client.get(
        f"/api/v1/projects/{project_id}/assets", params={"kind": "character"}
    ).json()
    assert [item["id"] for item in by_kind] == [character_id]

    by_name = client.get(
        f"/api/v1/projects/{project_id}/assets", params={"name": "林"}
    ).json()
    assert len(by_name) == 1 and by_name[0]["id"] == character_id

    active = client.get(
        f"/api/v1/projects/{project_id}/assets", params={"status": "active"}
    ).json()
    assert len(active) == 2


def test_recycle_and_restore(client: TestClient) -> None:
    project_id = _project(client)
    asset_id = _asset(client, project_id, "林墨")

    recycled = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/recycle",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert recycled.status_code == 200, recycled.text
    assert recycled.json()["status"] == "recycled"

    recycled_list = client.get(
        f"/api/v1/projects/{project_id}/assets", params={"status": "recycled"}
    ).json()
    assert [item["id"] for item in recycled_list] == [asset_id]

    # Recycling twice is rejected.
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/assets/{asset_id}/recycle",
            headers={CSRF_HEADER: _csrf(client)},
        ).status_code
        == 422
    )

    restored = client.post(
        f"/api/v1/projects/{project_id}/assets/{asset_id}/restore",
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "active"
