"""Add the verified SGLang MiniMax H3 Ref2VA protocol contract.

Revision ID: 20260930_0080
Revises: 20260929_0079
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0080"
down_revision: str | None = "20260929_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MANIFEST: dict[str, object] = {
    "manifest_version": "2026-09-30",
    "provider_type": "openai_compatible_media",
    "protocol_profile": "openai_media_v1",
    "model_id": "@contract/sglang-h3-ref2va-v1",
    "model_revision": "v1",
    "media_kind": "video",
    "display_name": "SGLang H3 参考素材生视频 (Ref2VA)",
    "lifecycle": "active",
    "catalog_source": "protocol_contract",
    "documented_at": "2026-09-30",
    "operations": {
        "video.generate": {
            "operation": "video.generate",
            "capabilities": [
                "video.reference.image",
                "video.reference.video",
                "video.reference.audio",
            ],
            "output_constraints": {
                "duration_seconds": 5,
                "aspect_ratio": {"allowed": ["9:16", "16:9"]},
                "native_audio": True,
            },
            "reference_constraints": {
                "reference_image": {"min": 0, "max": 1},
                "reference_video": {"min": 0, "max": 1},
                "reference_audio": {"min": 0, "max": 1},
            },
            "exclusive_groups": [{
                "name": "ref2va",
                "members": [["reference_image", "reference_video", "reference_audio"]],
            }],
        }
    },
    "option_schema": {"namespace": "", "options": {}},
}


def upgrade() -> None:
    encoded = json.dumps(_MANIFEST, sort_keys=True, separators=(",", ":"))
    op.get_bind().execute(
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
            "provider_type": _MANIFEST["provider_type"],
            "protocol_profile": _MANIFEST["protocol_profile"],
            "model_id": _MANIFEST["model_id"],
            "model_revision": _MANIFEST["model_revision"],
            "display_name": _MANIFEST["display_name"],
            "media_kind": _MANIFEST["media_kind"],
            "manifest": encoded,
            "option_schema": json.dumps(_MANIFEST["option_schema"]),
            "documented_at": date(2026, 9, 30),
            "manifest_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE provider_model_catalog_entries SET lifecycle = 'deprecated', updated_at = now()
            WHERE provider_type = 'openai_compatible_media'
              AND protocol_profile = 'openai_media_v1'
              AND model_id = '@contract/sglang-h3-ref2va-v1'
              AND model_revision = 'v1'
            """
        )
    )
