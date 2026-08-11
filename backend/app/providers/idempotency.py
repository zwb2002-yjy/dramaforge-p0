"""Request fingerprinting and idempotency helpers (V3 spec §45–§48).

Three distinct identities, never conflated:

- Intent idempotency: NodeRun ``idempotency_key`` (+ ``input_hash``) already
  exists for the Graph path and is reused (spec §43/§46). No second intent
  system is introduced.
- Semantic request fingerprint (this module): the normalized *semantic* request
  for one attempt — capability, requested model, inputs (by artifact identity,
  never signed URL), common options, native options (spec §45). Secret-free and
  transport-free by construction.
- Wire request fingerprint: computed inside the runtime over the redacted wire
  body (already persisted on ProviderOperation as ``request_fingerprint``).

Fingerprints never contain credentials, Authorization headers, or signed-URL
query tokens (spec §2.8/§64.3).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.providers.capabilities import Capability


def canonical_json(value: Any) -> str:
    """Canonical JSON serialization (spec §45.1): stable key order, compact
    separators, UTF-8-safe. ``default=str`` keeps UUID/Decimal JSON-serializable."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def sha256_of(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def semantic_request_fingerprint(
    *,
    capability: Capability,
    requested_model: str | None,
    inputs: dict[str, Any],
    common_options: dict[str, Any],
    native_options: dict[str, Any],
) -> str:
    """Canonical semantic fingerprint for one model execution attempt (spec §45).

    ``inputs`` must carry artifact *identity* (artifact_id + revision), never a
    signed URL or provider file token (spec §48).
    """
    payload: dict[str, Any] = {
        "capability": str(capability),
        "requested_model": requested_model,
        "inputs": inputs,
        "common_options": common_options,
        "native_options": native_options,
    }
    return sha256_of(canonical_json(payload))


def _artifact_identity(value: Any) -> Any:
    """Reduce an artifact reference to its stable identity only."""
    if isinstance(value, dict):
        return {key: _artifact_identity(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_artifact_identity(item) for item in value]
    # pydantic ArtifactRef-like objects expose artifact_id / revision.
    for attr in ("artifact_id", "revision"):
        if hasattr(value, attr):
            return getattr(value, attr)
    return value


def v3_request_fingerprint(
    capability: Capability,
    request: Any,
    *,
    model_id: str,
) -> str:
    """Build the semantic fingerprint of a V3 capability request.

    Inputs are reduced to artifact identity (prompt + artifact refs); common
    options are the top-level option fields; native options pass through. The
    result is deterministic across providers and free of secrets/URLs.
    """
    inputs: dict[str, Any] = {"prompt": getattr(request, "prompt", "")}
    option_fields = {
        "duration_seconds",
        "resolution",
        "aspect_ratio",
        "seed",
        "size",
        "max_tokens",
        "system",
        "voice",
        "language",
    }
    common_options = {
        key: value
        for key, value in request.model_dump().items()
        if key in option_fields and value is not None
    }
    native_options = dict(getattr(request, "native_options", {}) or {})
    # Reference-bearing fields are included by artifact identity only.
    for field in (
        "image",
        "first_frame",
        "last_frame",
        "reference_images",
        "reference_audio",
        "reference_videos",
    ):
        value = getattr(request, field, None)
        if value is not None:
            inputs[field] = _artifact_identity(value)
    return semantic_request_fingerprint(
        capability=capability,
        requested_model=model_id,
        inputs=inputs,
        common_options=common_options,
        native_options=native_options,
    )
