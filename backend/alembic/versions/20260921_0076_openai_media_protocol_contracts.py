"""Add protocol-level OpenAI-compatible image/video capability contracts.

Revision ID: 20260921_0076
Revises: 20260921_0075

The rows are capability contracts, not concrete supplier models. A workspace
connection discovers its concrete model ids from ``/v1/models`` and binds one
of these protocol contracts to the selected id.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0076"
down_revision: str | None = "20260921_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _hash_manifest(manifest: dict[str, object]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_CONTRACTS: tuple[dict[str, object], ...] = (
    {
        "manifest_version": "2026-09-21",
        "provider_type": "openai_compatible_media",
        "protocol_profile": "openai_media_v1",
        "model_id": "@contract/openai-image-v1",
        "model_revision": "v1",
        "media_kind": "image",
        "display_name": "OpenAI 兼容图像协议",
        "lifecycle": "active",
        "catalog_source": "protocol_contract",
        "documented_at": "2026-09-21",
        "operations": {
            "image.generate": {
                "operation": "image.generate",
                "capabilities": ["image.t2i", "image.i2i"],
                "output_constraints": {"response_format": "url", "size": "1024x1024"},
                "reference_constraints": {"reference_image": {"min": 0, "max": 1}},
                "exclusive_groups": [],
            }
        },
        "option_schema": {"namespace": "", "options": {}},
    },
    {
        "manifest_version": "2026-09-21",
        "provider_type": "openai_compatible_media",
        "protocol_profile": "openai_media_v1",
        "model_id": "@contract/openai-video-v1",
        "model_revision": "v1",
        "media_kind": "video",
        "display_name": "OpenAI 兼容异步视频协议",
        "lifecycle": "active",
        "catalog_source": "protocol_contract",
        "documented_at": "2026-09-21",
        "operations": {
            "video.generate": {
                "operation": "video.generate",
                "capabilities": ["video.i2v.first_frame"],
                "output_constraints": {
                    "duration_seconds": 5,
                    "resolution": "720x1280",
                    "aspect_ratio": "9:16",
                    "native_audio": False,
                },
                "reference_constraints": {"first_frame": {"min": 1, "max": 1}},
                "exclusive_groups": [],
            }
        },
        "option_schema": {"namespace": "", "options": {}},
    },
)


def upgrade() -> None:
    bind = op.get_bind()
    for manifest in _CONTRACTS:
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
                   :display_name, :media_kind, :lifecycle, :catalog_source,
                   CAST(:manifest AS json), CAST(:option_schema AS json),
                   CAST('{}' AS json), :documented_at, :manifest_hash, now(), now())
                ON CONFLICT (provider_type, protocol_profile, model_id, model_revision)
                DO UPDATE SET
                  lifecycle = EXCLUDED.lifecycle,
                  catalog_source = EXCLUDED.catalog_source,
                  capability_manifest_json = EXCLUDED.capability_manifest_json,
                  option_schema_json = EXCLUDED.option_schema_json,
                  documented_at = EXCLUDED.documented_at,
                  contract_manifest_hash = EXCLUDED.contract_manifest_hash,
                  updated_at = now()
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
                "lifecycle": manifest["lifecycle"],
                "catalog_source": manifest["catalog_source"],
                "manifest": json.dumps(manifest),
                "option_schema": json.dumps(manifest["option_schema"]),
                "documented_at": date.fromisoformat(str(manifest["documented_at"])),
                "manifest_hash": _hash_manifest(manifest),
            },
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE provider_model_catalog_entries
            SET lifecycle = 'deprecated', updated_at = now()
            WHERE provider_type = 'openai_compatible_media'
              AND protocol_profile = 'openai_media_v1'
              AND model_id IN ('@contract/openai-image-v1', '@contract/openai-video-v1')
              AND model_revision = 'v1'
            """
        )
    )
