"""Shared mapping from Provider HTTP failures to stable, secret-free codes.

The three BYOK adapters used to carry near-identical copies of these helpers,
which drifted (only MiniMax mapped 402, only Agnes understood an HTTP-date
Retry-After). One implementation keeps persisted ``error_code`` values and
retry hints identical regardless of which adapter made the call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx


def error_code_for_status(status_code: int) -> str:
    """Return the persisted error code for one Provider HTTP status."""
    if status_code == 400:
        return "PROVIDER_BAD_REQUEST"
    if status_code == 401:
        return "PROVIDER_AUTH_FAILED"
    if status_code == 402:
        return "PROVIDER_PAYMENT_REQUIRED"
    if status_code == 403:
        return "PROVIDER_FORBIDDEN"
    if status_code == 429:
        return "PROVIDER_RATE_LIMITED"
    if status_code >= 500:
        return "PROVIDER_UNAVAILABLE"
    return "PROVIDER_REQUEST_FAILED"


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse Retry-After as delay-seconds or an HTTP date; ignore junk."""
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        pass
    try:
        return max((parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return None
