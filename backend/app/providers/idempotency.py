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
    """Reduce an artifact reference to its stable identity only (spec §48).

    The identity is ``artifact_id`` + ``revision`` — never a signed URL, file
    token, or local path. A revision change must change the fingerprint, so the
    artifact_id is always returned together with the (possibly null) revision.
    """
    if isinstance(value, dict):
        return {key: _artifact_identity(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_artifact_identity(item) for item in value]
    artifact_id = getattr(value, "artifact_id", None)
    if artifact_id is not None:
        revision = getattr(value, "revision", None)
        return {
            "artifact_id": str(artifact_id),
            "revision": str(revision) if revision is not None else None,
        }
    return value


# Top-level fields that carry artifact references (reduced to identity in
# ``inputs``) and the primary content field (kept as ``prompt``). Every other
# top-level scalar field on the request contract lands in ``common_options`` —
# so the fingerprint is driven by the Request Contract shape, never by a second
# hardcoded option whitelist that can drift when a contract gains a field.
_REFERENCE_FIELDS = frozenset(
    {
        "image",
        "first_frame",
        "last_frame",
        "reference_images",
        "reference_audio",
        "reference_videos",
    }
)
_CONTENT_FIELDS = frozenset({"prompt", "text"})


def v3_request_fingerprint(
    capability: Capability,
    request: Any,
    *,
    model_id: str,
) -> str:
    """Build the semantic fingerprint of a V3 capability request.

    The serializer is contract-driven: it walks ``request.model_dump()`` and
    classifies each field. Artifact references are reduced to ``artifact_id +
    revision`` identity, the primary content field becomes ``inputs.prompt``,
    and every other set top-level field becomes a common option. Adding a field
    to a request contract automatically includes it in the fingerprint — there
    is no separate option whitelist to keep in sync.
    """
    data = request.model_dump(mode="json")
    inputs: dict[str, Any] = {}
    common_options: dict[str, Any] = {}
    for key, value in data.items():
        if key == "native_options":
            continue
        if key in _REFERENCE_FIELDS:
            if value is not None:
                inputs[key] = _artifact_identity(value)
        elif key in _CONTENT_FIELDS:
            inputs["prompt"] = value
        elif value is not None:
            common_options[key] = value
    return semantic_request_fingerprint(
        capability=capability,
        requested_model=model_id,
        inputs=inputs,
        common_options=common_options,
        native_options=dict(getattr(request, "native_options", {}) or {}),
    )
