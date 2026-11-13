"""Add immutable H3 FL2VA and expanded Ref2VA protocol contracts.

Revision ID: 20260930_0082
Revises: 20260930_0081
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0082"
down_revision: str | None = "20260930_0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMON = {
    "provider_type": "openai_compatible_media",
    "protocol_profile": "openai_media_v1",
    "media_kind": "video",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-30",
    "option_schema": {"namespace": "", "options": {}},
}

_MANIFESTS: list[dict[str, object]] = [
    {
        **_COMMON,
        "manifest_version": "2026-09-30-fl2va",
        "model_id": "@contract/sglang-h3-fl2va-v1",
        "model_revision": "v1",
        "display_name": "SGLang H3 文生/首尾帧 (FL2VA)",
        "operations": {
            "video.generate": {
                "operation": "video.generate",
                "capabilities": [
                    "video.t2v", "video.i2v.first_frame", "video.i2v.last_frame",
                ],
                "output_constraints": {
                    "modes": {
                        mode: {
                            "duration_seconds": 5,
                            "aspect_ratio": {"allowed": ["9:16", "16:9"]},
                            "native_audio": True,
                        }
                        for mode in (
                            "text_to_video", "first_frame", "last_frame", "first_last_frame"
                        )
                    }
                },
                "reference_constraints": {
                    "first_frame": {"min": 0, "max": 1},
                    "last_frame": {"min": 0, "max": 1},
                },
                "exclusive_groups": [],
            }
        },
    },
    {
        **_COMMON,
        "manifest_version": "2026-09-30-ref2va-v2",
        "model_id": "@contract/sglang-h3-ref2va-v1",
        "model_revision": "v2",
        "display_name": "SGLang H3 多素材参考 (Ref2VA)",
        "operations": {
            "video.generate": {
                "operation": "video.generate",
                "capabilities": [
                    "video.reference.image", "video.reference.video", "video.reference.audio",
                ],
                "output_constraints": {
                    "duration_seconds": 5,
                    "aspect_ratio": {"allowed": ["9:16", "16:9"]},
                    "native_audio": True,
                },
                "reference_constraints": {
                    "reference_image": {"min": 0, "max": 9},
                    "reference_video": {"min": 0, "max": 3},
                    "reference_audio": {"min": 0, "max": 3},
                },
                "exclusive_groups": [{
                    "name": "ref2va",
                    "members": [["reference_image", "reference_video", "reference_audio"]],
                }],
                "reference_media_limits": {
                    "maximum_files": 12,
                    "durations": {
                        role: {
                            "minimum_seconds": 2,
                            "maximum_seconds": 15,
                            "total_maximum_seconds": 15,
                        }
                        for role in ("reference_video", "reference_audio")
                    },
                },
            }
        },
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    for manifest in _MANIFESTS:
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        bind.execute(
            sa.text(
                """
                INSERT INTO provider_model_catalog_entries
                  (id, provider_type, protocol_profile, model_id, model_revision,
                   display_name, media_kind, lifecycle, catalog_source,
                   capability_manifest_json, option_schema_json, pricing_snapshot_json,
                   documented_at, contract_manifest_hash, created_at, updated_at)
                VALUES
                  (:id, :provider_type, :protocol_profile, :model_id, :model_revision,
                   :display_name, :media_kind, 'active', 'protocol_contract',
                   CAST(:manifest AS json), CAST(:option_schema AS json),
                   CAST('{}' AS json), :documented_at, :manifest_hash, now(), now())
                ON CONFLICT (provider_type, protocol_profile, model_id, model_revision)
                DO NOTHING
                """
            ),
            {
                "id": uuid4(),
                "provider_type": manifest["provider_type"],
                "protocol_profile": manifest["protocol_profile"],
                "model_id": manifest["model_id"],
                "model_revision": manifest["model_revision"],
                "display_name": manifest["display_name"],
                "media_kind": manifest["media_kind"],
                "manifest": encoded,
                "option_schema": json.dumps(manifest["option_schema"]),
                "documented_at": date(2026, 9, 30),
                "manifest_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            },
        )


def downgrade() -> None:
    for manifest in _MANIFESTS:
        op.get_bind().execute(
            sa.text(
                """
                UPDATE provider_model_catalog_entries
                SET lifecycle = 'deprecated', updated_at = now()
                WHERE provider_type = 'openai_compatible_media'
                  AND protocol_profile = 'openai_media_v1'
                  AND model_id = :model_id AND model_revision = :model_revision
                """
            ),
            {"model_id": manifest["model_id"], "model_revision": manifest["model_revision"]},
        )
