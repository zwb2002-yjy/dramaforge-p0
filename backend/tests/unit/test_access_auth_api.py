"""S1.1 access/session API tests via real TestClient + app factory."""

from __future__ import annotations

from app.shared.security import CSRF_HEADER
from fastapi.testclient import TestClient


def _csrf(client: TestClient) -> str:
    r = client.get("/api/v1/auth/csrf")
    assert r.status_code == 200
    token = r.json()["csrf_token"]
    assert token
    return token


def test_me_unauthenticated_returns_401(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


def test_register_login_me_cookie_roundtrip(client: TestClient) -> None:
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@example.com",
            "password": "password123",
            "display_name": "Alice",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["email"] == "alice@example.com"
    assert "password" not in body
    assert client.cookies.get("dramaforge_session")

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]

    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_create_org_requires_csrf(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "bob@example.com",
            "password": "password123",
            "display_name": "Bob",
        },
    )
    # Session cookie present but CSRF missing/wrong
    bad = client.post("/api/v1/organizations", json={"name": "Studio"})
    assert bad.status_code == 403
    assert bad.json()["code"] == "FORBIDDEN"

    csrf = _csrf(client)
    ok = client.post(
        "/api/v1/organizations",
        json={"name": "Studio"},
        headers={CSRF_HEADER: csrf},
    )
    assert ok.status_code == 201, ok.text
    org_id = ok.json()["id"]
    got = client.get(f"/api/v1/organizations/{org_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Studio"


def test_membership_create_and_list(client: TestClient) -> None:
    owner = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "password123",
            "display_name": "Owner",
        },
    )
    assert owner.status_code == 201
    # second user in separate client jar would be cleaner; register then logout, register member
    # use same client: create org as owner first
    csrf = _csrf(client)
    org = client.post(
        "/api/v1/organizations",
        json={"name": "Crew"},
        headers={CSRF_HEADER: csrf},
    )
    assert org.status_code == 201
    org_id = org.json()["id"]

    # register second user overwrites session to member
    member_reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "editor@example.com",
            "password": "password123",
            "display_name": "Ed",
        },
    )
    member_id = member_reg.json()["id"]
    # login back as owner
    client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "password123"},
    )
    csrf = _csrf(client)
    add = client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"user_id": member_id, "role": "editor"},
        headers={CSRF_HEADER: csrf},
    )
    assert add.status_code == 201, add.text
    assert add.json()["role"] == "editor"
    listed = client.get(f"/api/v1/organizations/{org_id}/members")
    assert listed.status_code == 200
    emails_roles = {(m["user_id"], m["role"]) for m in listed.json()}
    assert (member_id, "editor") in emails_roles
    assert len(listed.json()) == 2  # owner + editor


def test_migration_file_mirrors_access_tables() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260720_0001_s1_1_access_session.py"
    ).read_text(encoding="utf-8")
    for name in ("organizations", "users", "organization_members", "password_hash", "member_role"):
        assert name in text
