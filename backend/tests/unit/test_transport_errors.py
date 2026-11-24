"""One transport error vocabulary for every BYOK adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
from app.providers import agnes, minimax, volcengine
from app.providers.transport_errors import error_code_for_status, retry_after_seconds


def test_payment_required_is_not_reported_as_a_generic_failure() -> None:
    assert error_code_for_status(402) == "PROVIDER_PAYMENT_REQUIRED"
    assert error_code_for_status(403) == "PROVIDER_FORBIDDEN"
    assert error_code_for_status(400) == "PROVIDER_BAD_REQUEST"
    assert error_code_for_status(418) == "PROVIDER_REQUEST_FAILED"
    assert error_code_for_status(503) == "PROVIDER_UNAVAILABLE"


def test_all_adapters_delegate_to_the_same_vocabulary() -> None:
    for adapter in (agnes, minimax, volcengine):
        assert adapter._error_code(402) == "PROVIDER_PAYMENT_REQUIRED"
        assert adapter._error_code(429) == "PROVIDER_RATE_LIMITED"


def test_retry_after_accepts_seconds_and_http_date() -> None:
    seconds = httpx.Response(429, headers={"Retry-After": "17"})
    assert retry_after_seconds(seconds) == 17.0

    future = datetime.now(UTC) + timedelta(seconds=30)
    dated = httpx.Response(429, headers={"Retry-After": format_datetime(future, usegmt=True)})
    parsed = retry_after_seconds(dated)
    assert parsed is not None and 20 <= parsed <= 30

    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": "soon"})) is None
    assert retry_after_seconds(httpx.Response(429)) is None
