"""P4-11 ProviderOperation request_summary standardization (03 §41).

The ProviderOperation table is unchanged; only the ``request_summary`` JSON
structure is canonicalized so every operation carries:

- ``translation_report``      auditable requested/effective transformations
- ``effective_request_redacted`` the effective semantic request, secret-free
- ``reference_delivery``      how each reference was delivered (role/status)
- ``semantic_fingerprint``    deterministic sha256 of the canonical summary

Secret keys (api_key / authorization / ciphertext / ...) are rejected.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

from pydantic import JsonValue

_SECRET_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "authorization",
    "ciphertext",
    "password",
    "bearer",
    "secret",
    "download_url",
    "grant",
)


class RequestSummaryError(ValueError):
    """Raised when a request summary violates the contract."""


def validate_no_secrets(value: object, *, path: str = "summary") -> None:
    """Fail closed when any key contains a secret fragment."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise RequestSummaryError(f"request summary contains forbidden key: {path}.{key}")
            validate_no_secrets(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_no_secrets(child, path=f"{path}[{index}]")


def semantic_fingerprint(summary: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        summary,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_request_summary(
    *,
    translation_report: Mapping[str, Any] | None = None,
    effective_request_redacted: Mapping[str, Any] | None = None,
    reference_delivery: list[Mapping[str, Any]] | None = None,
    semantic_fingerprint_value: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, JsonValue]:
    """Build a canonical request_summary with the four required keys."""
    body: dict[str, Any] = {
        "translation_report": dict(translation_report or {}),
        "effective_request_redacted": dict(effective_request_redacted or {}),
        "reference_delivery": [dict(item) for item in (reference_delivery or [])],
    }
    if extra:
        for key, value in extra.items():
            body[str(key)] = value
    body["semantic_fingerprint"] = semantic_fingerprint_value or semantic_fingerprint(body)
    validate_no_secrets(body)
    return body


def normalize_request_summary(summary: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Validate one canonical summary; retired keys are never translated."""
    body: dict[str, Any] = dict(summary)
    if "effective_request" in body:
        raise RequestSummaryError("retired effective_request key is not accepted")
    body.setdefault("translation_report", {})
    body.setdefault("effective_request_redacted", {})
    body.setdefault("reference_delivery", [])
    body.setdefault("semantic_fingerprint", semantic_fingerprint(body))
    validate_no_secrets(body)
    return body
