"""S1.2 project create/read and dual-mode preference tests."""

from __future__ import annotations

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _register(client: TestClient, email: str) -> dict:
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _csrf(client: TestClient) -> str:
    return client.get("/api/v1/auth/csrf").json()["csrf_token"]


def test_create_and_get_project(client: TestClient) -> None:
    _register(client, "pm@example.com")
    csrf = _csrf(client)
    org = client.post(
        "/api/v1/organizations",
        json={"name": "OrgP"},
        headers={CSRF_HEADER: csrf},
    )
    assert org.status_code == 201
    org_id = org.json()["id"]
    csrf = _csrf(client)
    proj = client.post(
        "/api/v1/projects",
        json={
            "organization_id": org_id,
            "name": "ShowAlpha",
            "aspect_ratio": "9:16",
            "budget_limit": "100.50",
        },
        headers={CSRF_HEADER: csrf},
    )
    assert proj.status_code == 201, proj.text
    body = proj.json()
    assert body["name"] == "ShowAlpha"
    assert body["stage"] == "draft"
    assert body["aspect_ratio"] == "9:16"
    got = client.get(f"/api/v1/projects/{body['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]


def test_non_member_cannot_read_project(client: TestClient) -> None:
    _register(client, "owner2@example.com")
    csrf = _csrf(client)
    org = client.post(
        "/api/v1/organizations",
        json={"name": "PrivateOrg"},
        headers={CSRF_HEADER: csrf},
    )
    org_id = org.json()["id"]
    csrf = _csrf(client)
    proj = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Secret", "aspect_ratio": "16:9"},
        headers={CSRF_HEADER: csrf},
    )
    project_id = proj.json()["id"]
    _register(client, "intruder@example.com")
    denied = client.get(f"/api/v1/projects/{project_id}")
    assert denied.status_code == 403


def test_experience_mode_switch_same_project(client: TestClient) -> None:
    _register(client, "mode@example.com")
    csrf = _csrf(client)
    org = client.post(
        "/api/v1/organizations",
        json={"name": "ModeOrg"},
        headers={CSRF_HEADER: csrf},
    )
    csrf = _csrf(client)
    proj = client.post(
        "/api/v1/projects",
        json={
            "organization_id": org.json()["id"],
            "name": "Shared",
            "aspect_ratio": "9:16",
        },
        headers={CSRF_HEADER: csrf},
    )
    pid = proj.json()["id"]
    csrf = _csrf(client)
    quick = client.put(
        f"/api/v1/projects/{pid}/preferences/experience-mode",
        json={"experience_mode": "quick"},
        headers={CSRF_HEADER: csrf},
    )
    assert quick.status_code == 200
    assert quick.json()["experience_mode"] == "quick"
    assert quick.json()["project_id"] == pid
    csrf = _csrf(client)
    wb = client.put(
        f"/api/v1/projects/{pid}/preferences/experience-mode",
        json={"experience_mode": "workbench"},
        headers={CSRF_HEADER: csrf},
    )
    assert wb.status_code == 200
    assert wb.json()["experience_mode"] == "workbench"
