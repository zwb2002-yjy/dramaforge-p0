"""Password hashing, signed session cookies, and CSRF tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any
from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE = "dramaforge_session"
CSRF_COOKIE = "dramaforge_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14


def hash_password(password: str) -> str:
    """Return a salted PBKDF2-SHA256 password hash string."""
    if not password:
        raise ValueError("password must be non-empty")
    salt = secrets.token_hex(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
    )
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verify against `hash_password` output."""
    try:
        algo, iter_s, salt, hex_digest = password_hash.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_s)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
    )
    return hmac.compare_digest(digest.hex(), hex_digest)


def _serializer(secret: str, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=secret, salt=salt)


def issue_session_token(*, user_id: UUID, secret: str) -> str:
    """Create a signed session token for the given user."""
    return _serializer(secret, "dramaforge-session").dumps({"uid": str(user_id)})


def parse_session_token(token: str, *, secret: str) -> UUID:
    """Parse and validate a session token; raise ValueError if invalid."""
    try:
        data: dict[str, Any] = _serializer(secret, "dramaforge-session").loads(
            token, max_age=SESSION_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired) as exc:
        raise ValueError("invalid or expired session") from exc
    uid = data.get("uid")
    if not isinstance(uid, str):
        raise ValueError("invalid session payload")
    try:
        return UUID(uid)
    except ValueError as exc:
        raise ValueError("invalid user id in session") from exc


def issue_csrf_token(*, secret: str) -> str:
    """Issue a random CSRF token bound into a signed envelope."""
    nonce = secrets.token_urlsafe(32)
    return _serializer(secret, "dramaforge-csrf").dumps({"n": nonce})


def verify_csrf_token(*, cookie_token: str | None, header_token: str | None, secret: str) -> bool:
    """Double-submit CSRF: cookie and header must match and verify."""
    if not cookie_token or not header_token:
        return False
    if not hmac.compare_digest(cookie_token, header_token):
        return False
    try:
        data = _serializer(secret, "dramaforge-csrf").loads(
            cookie_token, max_age=SESSION_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired):
        return False
    return isinstance(data, dict) and isinstance(data.get("n"), str)
