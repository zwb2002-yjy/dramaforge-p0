"""Private workspace and session API tests via the application factory."""

from __future__ import annotations

import pytest
from app.config import clear_settings_cache
from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _register(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "display_name": email.partition("@")[0]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_me_unauthenticated_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_clean_instance_bootstraps_one_owner_then_closes_registration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PUBLIC_REGISTRATION_ENABLED", "false")
    clear_settings_cache()

    before = client.get("/api/v1/auth/bootstrap-status")
    assert before.status_code == 200
    assert before.json() == {
        "owner_initialized": False,
        "registration_available": True,
        "public_registration_enabled": False,
    }

    owner = _register(client, "first-owner@example.com")
    assert owner["email"] == "first-owner@example.com"

    after = client.get("/api/v1/auth/bootstrap-status")
    assert after.status_code == 200
    assert after.json() == {
        "owner_initialized": True,
        "registration_available": False,
        "public_registration_enabled": False,
    }

    rejected = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second-owner@example.com",
            "password": "password123",
            "display_name": "second",
        },
    )
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "REGISTRATION_CLOSED"


def test_register_creates_one_owned_default_workspace_and_login_roundtrip(
    client: TestClient,
) -> None:
    user = _register(client, "alice@example.com")
    assert user["email"] == "alice@example.com"
    assert "password" not in user
    assert client.cookies.get("dramaforge_session")

    workspaces = client.get("/api/v1/workspaces")
    assert workspaces.status_code == 200
    assert len(workspaces.json()) == 1
    assert workspaces.json()[0]["owner_user_id"] == user["id"]
    assert workspaces.json()[0]["name"] == "\u6211\u7684\u521b\u4f5c\u7a7a\u95f4"

    assert client.get("/api/v1/auth/me").json()["id"] == user["id"]
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "password123"}
    ).status_code == 200


def test_secure_cookie_is_explicit_and_not_implied_by_production(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("WORKER_TOKEN", "w" * 48)
    monkeypatch.setenv("BYOK_FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    clear_settings_cache()

    response = client.get("/api/v1/auth/csrf")

    assert response.status_code == 200
    assert "secure" not in response.headers["set-cookie"].lower()


def test_workspace_create_rename_and_empty_delete_require_csrf(client: TestClient) -> None:
    _register(client, "bob@example.com")
    assert client.post("/api/v1/workspaces", json={"name": "Studio"}).status_code == 403

    created = client.post(
        "/api/v1/workspaces", json={"name": "Studio"}, headers={CSRF_HEADER: _csrf(client)}
    )
    assert created.status_code == 201, created.text
    workspace_id = created.json()["id"]
    assert client.get(f"/api/v1/workspaces/{workspace_id}").json()["name"] == "Studio"

    renamed = client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Renamed"},
        headers={CSRF_HEADER: _csrf(client)},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed"
    assert client.delete(
        f"/api/v1/workspaces/{workspace_id}", headers={CSRF_HEADER: _csrf(client)}
    ).status_code == 204


def test_other_user_cannot_read_rename_or_delete_workspace(client: TestClient) -> None:
    _register(client, "owner@example.com")
    created = client.post(
        "/api/v1/workspaces", json={"name": "Private"}, headers={CSRF_HEADER: _csrf(client)}
    )
    assert created.status_code == 201
    workspace_id = created.json()["id"]

    _register(client, "intruder@example.com")
    assert client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 403
    assert client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Stolen"},
        headers={CSRF_HEADER: _csrf(client)},
    ).status_code == 403
    assert client.delete(
        f"/api/v1/workspaces/{workspace_id}", headers={CSRF_HEADER: _csrf(client)}
    ).status_code == 403


def test_access_migration_contains_owned_workspaces_only() -> None:
    from pathlib import Path

    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    migration_text = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in versions.glob("*.py")
    ).lower()
    for name in (
        "workspaces",
        "users",
        "instance_bootstrap_state",
        "owner_user_id",
        "password_hash",
    ):
        assert name in migration_text
    for name in (
        "organizations",
        "organization_members",
        "organization_id",
        "project_members",
        "workspace_members",
        "member_role",
    ):
        assert name not in migration_text
