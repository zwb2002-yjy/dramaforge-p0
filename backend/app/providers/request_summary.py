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
                raise RequestSummaryError(
                    f"request summary contains forbidden key: {path}.{key}"
                )
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
    """Coerce an existing request_summary into the canonical four-key shape.

    Existing keys such as ``effective_request`` / ``reference_artifact_ids`` are
    folded into the canonical keys when the canonical ones are absent.
    """
    body: dict[str, Any] = dict(summary)
    if "translation_report" not in body:
        body["translation_report"] = {}
    if "effective_request_redacted" not in body:
        # Keep the legacy ``effective_request`` key for backward compatibility
        # and add the canonical redacted key (03 §41 requires the canonical key).
        body["effective_request_redacted"] = body.get("effective_request", {})
    if "reference_delivery" not in body:
        delivery: list[dict[str, Any]] = []
        artifact_ids = body.get("reference_artifact_ids")
        if isinstance(artifact_ids, list):
            for item in artifact_ids:
                delivery.append(
                    {"role": "reference", "artifact_id": str(item), "status": "delivered"}
                )
        body["reference_delivery"] = delivery
    if "semantic_fingerprint" not in body:
        body["semantic_fingerprint"] = semantic_fingerprint(body)
    validate_no_secrets(body)
    return body
