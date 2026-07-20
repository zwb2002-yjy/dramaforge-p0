"""Unit tests for password and session/CSRF helpers (shipped security module)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.shared.security import (
    hash_password,
    issue_csrf_token,
    issue_session_token,
    parse_session_token,
    verify_csrf_token,
    verify_password,
)

SECRET = "unit-test-session-secret-min16"


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong", hashed)


def test_session_token_roundtrip() -> None:
    uid = uuid4()
    token = issue_session_token(user_id=uid, secret=SECRET)
    assert parse_session_token(token, secret=SECRET) == uid


def test_session_token_rejects_tamper() -> None:
    uid = uuid4()
    token = issue_session_token(user_id=uid, secret=SECRET)
    with pytest.raises(ValueError):
        parse_session_token(token + "x", secret=SECRET)


def test_csrf_double_submit() -> None:
    token = issue_csrf_token(secret=SECRET)
    assert verify_csrf_token(cookie_token=token, header_token=token, secret=SECRET)
    assert not verify_csrf_token(cookie_token=token, header_token="other", secret=SECRET)
    assert not verify_csrf_token(cookie_token=None, header_token=token, secret=SECRET)
