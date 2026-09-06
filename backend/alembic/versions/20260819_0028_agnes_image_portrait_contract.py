"""append Agnes Image 2.1 Flash native portrait catalog contract

Revision ID: 20260819_0028
Revises: 20260817_0027
Create Date: 2026-08-19

The v1 row remains immutable for historical ProviderOperation recovery. New
submissions use v2 only after a fresh binding-scoped account Probe.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_0028"
down_revision: str | None = "20260817_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _hash_manifest(manifest: dict[str, object]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_AGNES_IMAGE_V2_MANIFEST: dict[str, object] = {
    "manifest_version": "2026-08-19",
    "provider_type": "agnes",
    "protocol_profile": "agnes_cn_v1",
    "model_id": "agnes-image-2.1-flash",
    "model_revision": "v2",
    "media_kind": "image",
    "display_name": "Agnes Image Flash",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-19",
    "operations": {
        "image.generate": {
            "operation": "image.generate",
            "capabilities": ["image.t2i", "image.i2i"],
            "output_constraints": {
                "size": "1K",
                "aspect_ratio": "9:16",
                "width": 736,
                "height": 1312,
                "response_format": "url",
            },
            "reference_constraints": {"reference_image": {"min": 0, "max": 1}},
            "exclusive_groups": [],
        }
    },
    "option_schema": {"namespace": "", "options": {}},
}


def upgrade() -> None:
    manifest = _AGNES_IMAGE_V2_MANIFEST
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE provider_model_catalog_entries
            SET lifecycle = 'deprecated', updated_at = now()
            WHERE provider_type = 'agnes'
              AND protocol_profile = 'agnes_cn_v1'
              AND model_id = 'agnes-image-2.1-flash'
              AND model_revision = 'v1'
            """
        )
    )
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
               :display_name, :media_kind, 'active', 'official_static',
               CAST(:manifest AS json), CAST(:option_schema AS json),
               CAST('{}' AS json), :documented_at, :manifest_hash, now(), now())
            ON CONFLICT (provider_type, protocol_profile, model_id, model_revision)
            DO UPDATE SET lifecycle = 'active', updated_at = now()
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
            "manifest": json.dumps(manifest),
            "option_schema": json.dumps(manifest["option_schema"]),
            "documented_at": date.fromisoformat(str(manifest["documented_at"])),
            "manifest_hash": _hash_manifest(manifest),
        },
    )


def downgrade() -> None:
    # Keep a referenced v2 row for historical recovery; it simply becomes
    # ineligible for new submissions after the downgrade.
    op.execute(
        """
        UPDATE provider_model_catalog_entries
        SET lifecycle = 'deprecated', updated_at = now()
        WHERE provider_type = 'agnes'
          AND protocol_profile = 'agnes_cn_v1'
          AND model_id = 'agnes-image-2.1-flash'
          AND model_revision = 'v2'
        """
    )
    op.execute(
        """
        UPDATE provider_model_catalog_entries
        SET lifecycle = 'active', updated_at = now()
        WHERE provider_type = 'agnes'
          AND protocol_profile = 'agnes_cn_v1'
          AND model_id = 'agnes-image-2.1-flash'
          AND model_revision = 'v1'
        """
    )
