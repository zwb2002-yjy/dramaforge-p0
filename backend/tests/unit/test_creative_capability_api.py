"""Creative capability catalog is a projection of the backend registries."""

from __future__ import annotations

from uuid import uuid4

from app.director.creative_capabilities.packs_library import GENRE_PROFILES, STYLE_PACKS
from app.director.creative_capabilities.shot_language_library import (
    QUALITY_POLICIES,
    SHOT_LANGUAGE_PACKS,
)
from app.director.creative_capabilities.skill_library import BASELINE_SKILLS
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/csrf").json()["csrf_token"])


def _project(client: TestClient) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"catalog-{uuid4().hex}@example.com",
            "password": "password123",
            "display_name": "Catalog Owner",
        },
    )
    assert registered.status_code in {200, 201}, registered.text
    workspace_id = str(client.get("/api/v1/workspaces").json()[0]["id"])
    client.headers["X-Workspace-Id"] = workspace_id
    created = client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": "Catalog Project", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert created.status_code in {200, 201}, created.text
    return str(created.json()["id"])


def test_catalog_projects_every_backend_registry(client: TestClient) -> None:
    project_id = _project(client)
    response = client.get(f"/api/v1/projects/{project_id}/creative-capabilities/catalog")
    assert response.status_code == 200, response.text
    catalog = response.json()

    assert [item["key"] for item in catalog["genres"]] == [
        item.genre_key for item in GENRE_PROFILES
    ]
    assert [item["key"] for item in catalog["styles"]] == [item.style_key for item in STYLE_PACKS]
    assert [item["key"] for item in catalog["shot_languages"]] == [
        item.pack_key for item in SHOT_LANGUAGE_PACKS
    ]
    assert [item["key"] for item in catalog["quality_policies"]] == [
        item.policy_key for item in QUALITY_POLICIES
    ]
    assert [item["key"] for item in catalog["skills"]] == [
        item.skill_key for item in BASELINE_SKILLS
    ]
    assert all(item["display_name"] and item["description"] for item in catalog["skills"])


def test_creation_choices_use_the_same_catalog_and_persist_via_api(client: TestClient) -> None:
    assert client.get("/api/v1/creative-capabilities/catalog").status_code in {401, 403}
    project_id = _project(client)
    catalog = client.get("/api/v1/creative-capabilities/catalog")
    assert catalog.status_code == 200, catalog.text
    assert (
        catalog.json()
        == client.get(f"/api/v1/projects/{project_id}/creative-capabilities/catalog").json()
    )
    genre_key = catalog.json()["genres"][0]["key"]
    style_key = catalog.json()["styles"][0]["key"]
    response = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": client.headers["X-Workspace-Id"],
            "name": "Chosen style",
            "aspect_ratio": "9:16",
            "genre_key": genre_key,
            "style_key": style_key,
        },
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert response.status_code == 201, response.text
    profile = response.json()["creative_profile"]
    assert profile["selected_genre"] == genre_key
    assert profile["selected_style_ids"] == [style_key]
    assert profile["strategy_snapshot"]["creative_capabilities"]["compiled_hash"]
