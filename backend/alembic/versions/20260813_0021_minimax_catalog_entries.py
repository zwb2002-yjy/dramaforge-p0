"""append frozen MiniMax image-01 and H3 catalog contracts

Revision ID: 20260813_0021
Revises: 20260813_0020
Create Date: 2026-08-13

This migration deliberately carries its own immutable payload. Historical
migrations must not import the evolving runtime catalog.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0021"
down_revision: str | None = "20260813_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _hash_manifest(manifest: dict[str, object]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_MINIMAX_MANIFESTS: tuple[dict[str, object], ...] = (
    {
        "manifest_version": "2026-08-13",
        "provider_type": "minimax",
        "protocol_profile": "minimax_cn_v1",
        "model_id": "image-01",
        "model_revision": "v1",
        "media_kind": "image",
        "display_name": "MiniMax Image 01",
        "lifecycle": "active",
        "catalog_source": "official_static",
        "documented_at": "2026-08-13",
        "operations": {
            "image.generate": {
                "operation": "image.generate",
                "capabilities": ["image.i2i"],
                "output_constraints": {
                    "size": "1024x1024",
                    "aspect_ratio": "1:1",
                    "response_format": "url",
                    "n": 1,
                },
                "reference_constraints": {"reference_image": {"min": 1, "max": 1}},
                "exclusive_groups": [],
            }
        },
        "option_schema": {"namespace": "", "options": {}},
    },
    {
        "manifest_version": "2026-08-13",
        "provider_type": "minimax",
        "protocol_profile": "minimax_cn_v1",
        "model_id": "MiniMax-H3",
        "model_revision": "v1",
        "media_kind": "video",
        "display_name": "MiniMax H3",
        "lifecycle": "active",
        "catalog_source": "official_static",
        "documented_at": "2026-08-13",
        "operations": {
            "video.generate": {
                "operation": "video.generate",
                "capabilities": ["video.i2v.first_frame"],
                "output_constraints": {
                    "resolution": "768P",
                    "duration_seconds": 5,
                    "aspect_ratio": "adaptive",
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
    for manifest in _MINIMAX_MANIFESTS:
        documented_at = date.fromisoformat(str(manifest["documented_at"]))
        option_schema = manifest["option_schema"]
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
                "lifecycle": manifest["lifecycle"],
                "catalog_source": manifest["catalog_source"],
                "manifest": json.dumps(manifest),
                "option_schema": json.dumps(option_schema),
                "documented_at": documented_at,
                "manifest_hash": _hash_manifest(manifest),
            },
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM provider_model_catalog_entries
        WHERE provider_type = 'minimax'
          AND protocol_profile = 'minimax_cn_v1'
          AND model_id IN ('image-01', 'MiniMax-H3')
          AND model_revision = 'v1'
        """
    )
