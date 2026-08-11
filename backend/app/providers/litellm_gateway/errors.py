"""Classified LiteLLM gateway failures (spec §63–§65, §97–§98).

The gateway client classifies every transport/HTTP failure into the normalized
V3 :class:`ProviderErrorCode` vocabulary; business code never branches on raw
status text. ``read timeout after submit`` escalates to
:class:`SubmissionOutcomeUnknownError` because the request may have been
accepted and billed (spec §64/§65) — never auto re-POST from that state.
"""

from __future__ import annotations

from app.providers.errors import (
    ProviderError,
    ProviderErrorCode,
    SubmissionOutcomeUnknownError,
)

__all__ = [
    "classify_http",
    "gateway_auth_failed",
    "gateway_model_unavailable",
    "gateway_unavailable",
    "SubmissionOutcomeUnknownError",
]


def gateway_unavailable(detail: str) -> ProviderError:
    """Gateway unreachable / 5xx / connection-level failure (spec §63)."""
    return ProviderError(
        ProviderErrorCode.PROVIDER_UNAVAILABLE,
        detail,
        status_code=503,
    )


def gateway_auth_failed(detail: str) -> ProviderError:
    """401/403 from the gateway — the DramaForge Virtual/Master key is bad."""
    return ProviderError(
        ProviderErrorCode.AUTH_FAILED,
        detail,
        status_code=401,
    )


def gateway_model_unavailable(detail: str) -> ProviderError:
    """The requested logical model alias does not exist on the gateway."""
    return ProviderError(
        ProviderErrorCode.MODEL_UNAVAILABLE,
        detail,
        status_code=404,
    )


def gateway_rate_limited(detail: str) -> ProviderError:
    return ProviderError(
        ProviderErrorCode.RATE_LIMITED,
        detail,
        status_code=429,
    )


def gateway_invalid_request(detail: str) -> ProviderError:
    return ProviderError(
        ProviderErrorCode.INVALID_REQUEST,
        detail,
        status_code=400,
    )


def classify_http(status: int, message: str) -> ProviderError:
    """Map a gateway HTTP status (+ error message) to a typed ProviderError.

    LiteLLM returns 400 for some semantic failures (unknown model, key/DB
    misconfig), so message heuristics run after the explicit status buckets.
    """
    if status in (401, 403):
        return gateway_auth_failed(f"LiteLLM gateway auth failed (HTTP {status}): {message}")
    if status == 404:
        return gateway_model_unavailable(
            f"LiteLLM model not found (HTTP {status}): {message}"
        )
    if status == 429:
        return gateway_rate_limited(
            f"LiteLLM gateway rate limited (HTTP {status}): {message}"
        )
    if 500 <= status < 600:
        return gateway_unavailable(
            f"LiteLLM gateway error (HTTP {status}): {message}"
        )
    lowered = (message or "").lower()
    if "invalid model name" in lowered or "model not found" in lowered:
        return gateway_model_unavailable(message)
    if "no connected db" in lowered or "connect to database" in lowered:
        return gateway_unavailable(message)
    return gateway_invalid_request(
        f"LiteLLM gateway rejected request (HTTP {status}): {message}"
    )
