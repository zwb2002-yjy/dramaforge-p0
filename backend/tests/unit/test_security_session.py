"""Unit tests for password and session/CSRF helpers (shipped security module)."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from app.shared.security import (
    PASSWORD_HASH_ITERATIONS,
    hash_password,
    issue_csrf_token,
    issue_session_token,
    parse_session_token,
    verify_csrf_token,
    verify_password,
)

SECRET = "unit-test-session-secret-min16"


def test_new_password_hashes_use_current_iteration_count() -> None:
    hashed = hash_password("correct horse battery")
    assert int(hashed.split("$")[1]) == PASSWORD_HASH_ITERATIONS >= 600_000


def test_legacy_password_hash_still_verifies() -> None:
    salt = "legacy-salt"
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", b"old password", salt.encode("ascii"), iterations)
    legacy = f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"
    assert verify_password("old password", legacy)
    assert not verify_password("wrong", legacy)


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


@pytest.mark.parametrize("cookie,header", [("valid-ascii", "é"), ("é", "é")])
def test_non_ascii_csrf_is_rejected_without_server_error(cookie, header):
    assert not verify_csrf_token(cookie_token=cookie, header_token=header, secret=SECRET)
