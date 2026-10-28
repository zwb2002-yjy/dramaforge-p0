"""Known/missing/inactive identities use the same real password KDF path."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.access.models import User
from app.access.service import AccessService
from app.shared.errors import UnauthorizedError
from app.shared.security import hash_password


@pytest.mark.parametrize("state", ["missing", "inactive", "wrong_password", "valid"])
async def test_authentication_does_exactly_one_password_kdf_for_every_identity(monkeypatch, state):
    from app.shared import security

    user = (
        None
        if state == "missing"
        else User(
            email="user@example.com",
            display_name="User",
            is_active=state != "inactive",
            password_hash=hash_password("correct-password"),
        )
    )
    service = AccessService(MagicMock())
    service._repo.get_user_by_email = AsyncMock(return_value=user)
    actual = security.hashlib.pbkdf2_hmac
    calls = []

    def tracked(*args, **kwargs):
        calls.append(args[3])
        return actual(*args, **kwargs)

    monkeypatch.setattr(security.hashlib, "pbkdf2_hmac", tracked)
    password = "wrong-password" if state == "wrong_password" else "correct-password"
    if state == "valid":
        assert await service.authenticate(email="User@example.com", password=password) is user
    else:
        with pytest.raises(UnauthorizedError, match="invalid credentials"):
            await service.authenticate(email="User@example.com", password=password)
    assert calls == [120_000]


def test_login_failures_have_identical_public_response_for_known_and_unknown_user(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "known@example.com",
            "password": "correct-password",
            "display_name": "Known",
        },
    )
    assert registered.status_code == 201
    known = client.post(
        "/api/v1/auth/login",
        json={
            "email": "known@example.com",
            "password": "wrong-password",
        },
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={
            "email": "unknown@example.com",
            "password": "wrong-password",
        },
    )
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()
