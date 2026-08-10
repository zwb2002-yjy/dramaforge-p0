"""Seed model capability manifests and their stable contract hash.

This module is the single source of truth for the *current* model catalog. It
is imported by the runtime (``catalog_service`` reads only, never writes) and by
the tests. The Alembic migration ``20260810_0015`` does **not** import this
module: it carries a frozen snapshot (``alembic/versions/_seeds_0015.py``) so
historical migrations stay reproducible. Tests assert the migration seed hash
equals the hash of this module's manifests.

Only capabilities already covered by a Contract Test, account Probe, or quality
evidence are declared. Adding an unverified capability here is a bug.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

MANIFEST_VERSION = "2026-08-10"

# ---------------------------------------------------------------------------
# Contract hash: stable canonical JSON sha256. Order- and whitespace-insensitive.
# ---------------------------------------------------------------------------


def hash_manifest(manifest_dict: dict[str, Any]) -> str:
    """Stable sha256 over the canonical JSON of a manifest dict."""
    raw = json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _operation(
    kind: str,
    *,
    capabilities: list[str],
    output_constraints: dict[str, Any] | None = None,
    reference_constraints: dict[str, dict[str, int]] | None = None,
    exclusive_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    op: dict[str, Any] = {
        "operation": kind,
        "capabilities": capabilities,
        "output_constraints": output_constraints or {},
        "reference_constraints": {
            role: {"min": int(v["min"]), "max": int(v["max"])}
            for role, v in (reference_constraints or {}).items()
        },
        "exclusive_groups": exclusive_groups or [],
    }
    return op


def _manifest(
    *,
    provider_type: str,
    protocol_profile: str,
    model_id: str,
    model_revision: str,
    media_kind: str,
    display_name: str,
    operations: dict[str, dict[str, Any]],
    option_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "provider_type": provider_type,
        "protocol_profile": protocol_profile,
        "model_id": model_id,
        "model_revision": model_revision,
        "media_kind": media_kind,
        "display_name": display_name,
        "lifecycle": "active",
        "catalog_source": "official_static",
        "documented_at": date.today().isoformat(),
        "operations": operations,
        "option_schema": option_schema
        or {"namespace": "", "options": {}},
    }


# ---------------------------------------------------------------------------
# Current seed manifests. Only verified contracts; wire details live in
# fixtures/providers/contracts/*.json (same hash — tests enforce equality).
# ---------------------------------------------------------------------------

SEED_MANIFESTS: list[dict[str, Any]] = [
    # Agnes China image (Image 2.x). Wire: POST /v1/images/generations
    #   {model, prompt, size, extra_body:{response_format:"url", image:[data_uri]}}.
    # Verified 2026-08-04/05 against wiki.agnes-ai.cn + vendor support.
    _manifest(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-image-2.1-flash",
        model_revision="v1",
        media_kind="image",
        display_name="Agnes Image Flash",
        operations={
            "image.generate": _operation(
                "image.generate",
                capabilities=["image.t2i", "image.i2i"],
                output_constraints={
                    "size": "1024x768",
                    "response_format": "url",
                },
                reference_constraints={
                    "reference_image": {"min": 0, "max": 1},
                },
            )
        },
    ),
    # Agnes China video (Video V2.0). Wire: POST /v1/videos
    #   {model, prompt, num_frames, frame_rate, height, width, image|extra_body}.
    # Only first-frame I2V is declared; keyframes / last_frame / audio have no
    # accepted product-path contract evidence yet.
    _manifest(
        provider_type="agnes",
        protocol_profile="agnes_cn_v1",
        model_id="agnes-video-v2.0",
        model_revision="v1",
        media_kind="video",
        display_name="Agnes Video V2.0",
        operations={
            "video.generate": _operation(
                "video.generate",
                capabilities=["video.i2v"],
                output_constraints={
                    "num_frames": {"allowed": [121]},
                    "frame_rate": {"allowed": [24]},
                    "height": 1280,
                    "width": 720,
                    "aspect_ratio": "9:16",
                },
                reference_constraints={
                    "first_frame": {"min": 1, "max": 1},
                },
            )
        },
    ),
    # Volcengine Ark Seedream image. Wire: POST {base}/images/generations
    #   {model, prompt, size, response_format, watermark, seed?, image?:[url]}.
    # Verified 2026-08-07 via official Ark docs + arkcli +gen --dry-run.
    _manifest(
        provider_type="volcengine",
        protocol_profile="ark_cn_v1",
        model_id="doubao-seedream-4-0-250828",
        model_revision="v1",
        media_kind="image",
        display_name="Seedream 4.0",
        operations={
            "image.generate": _operation(
                "image.generate",
                capabilities=["image.t2i", "image.i2i"],
                output_constraints={
                    "size": "2048x2048",
                    "response_format": "url",
                    "watermark": False,
                },
                reference_constraints={
                    "reference_image": {"min": 0, "max": 1},
                },
            )
        },
    ),
    # Volcengine Ark Seedance video. Wire: POST {base}/contents/generations/tasks
    #   {model, content:[{type:text},{type:image_url, image_url:{url},
    #   role:"first_frame"}]}. duration/ratio/audio are NOT declared: no accepted
    #   account-verified evidence for this fixed catalog revision (design §7.2).
    _manifest(
        provider_type="volcengine",
        protocol_profile="ark_cn_v1",
        model_id="doubao-seedance-1-0-pro-250528",
        model_revision="v1",
        media_kind="video",
        display_name="Seedance 1.0 Pro",
        operations={
            "video.generate": _operation(
                "video.generate",
                capabilities=["video.i2v"],
                reference_constraints={
                    "first_frame": {"min": 1, "max": 1},
                },
            )
        },
    ),
]


def seed_manifests_for(*, provider_type: str) -> list[dict[str, Any]]:
    return [m for m in SEED_MANIFESTS if m["provider_type"] == provider_type]
