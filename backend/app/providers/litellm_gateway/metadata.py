"""Allowlisted LiteLLM response metadata (spec §47–§48, §99–§100).

Only an explicit allowlist of cost / retry / fallback / latency / identity
headers is recorded into ``provider_metadata``. Authorization, Cookie, and any
unknown header are never stored (§48/§121). Cost prefers the primary
``x-litellm-response-cost`` header and falls back to
``x-litellm-response-cost-original`` when the primary is absent (both are
emitted depending on how cost is computed by the pinned version).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

RESPONSE_HEADER_ALLOWLIST: dict[str, str] = {
    "x-litellm-response-cost": "litellm_response_cost",
    "x-litellm-response-cost-original": "litellm_response_cost_original",
    "x-litellm-attempted-retries": "litellm_attempted_retries",
    "x-litellm-attempted-fallbacks": "litellm_attempted_fallbacks",
    "x-litellm-response-duration-ms": "litellm_response_duration_ms",
    "x-litellm-overhead-duration-ms": "litellm_overhead_duration_ms",
    "x-litellm-call-id": "request_id",
    "x-litellm-model-id": "litellm_model_id",
    "x-litellm-model-name": "litellm_model_name",
    "x-litellm-model-group": "litellm_model_group",
    "x-litellm-version": "litellm_version",
}

_HEADERS_GET = ("get", "__getitem__")


def parse_allowlisted_headers(headers: Any) -> dict[str, Any]:
    """Map the allowlisted subset of gateway response headers into
    provider_metadata-safe values (no secrets, keys normalized)."""
    out: dict[str, Any] = {}
    for raw_name, key in RESPONSE_HEADER_ALLOWLIST.items():
        value = _header_value(headers, raw_name)
        if value is None or value == "":
            continue
        if "cost" in key or "duration" in key:
            parsed = _decimal(value)
            out[key] = parsed if parsed is not None else value
        elif "retries" in key or "fallbacks" in key:
            parsed_int = _int(value)
            out[key] = parsed_int if parsed_int is not None else value
        else:
            out[key] = value
    return out


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is not None:
        try:
            value = getter(name)
        except TypeError:
            value = None
        if value is not None:
            return str(value)
    if isinstance(headers, dict):
        value = headers.get(name) or headers.get(name.title())
        return str(value) if value is not None else None
    return None


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _int(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
