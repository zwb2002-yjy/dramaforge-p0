"""append the frozen Seedance 2.0 first-frame I2V catalog contract

Revision ID: 20260817_0027
Revises: 20260814_0026
Create Date: 2026-08-17

This migration carries an immutable payload. Historical migrations must not
import the evolving runtime catalog.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0027"
down_revision: str | None = "20260814_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _hash_manifest(manifest: dict[str, object]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_SEEDANCE_2_MANIFEST: dict[str, object] = {
    "manifest_version": "2026-08-17",
    "provider_type": "volcengine",
    "protocol_profile": "ark_cn_v1",
    "model_id": "doubao-seedance-2-0-260128",
    "model_revision": "v1",
    "media_kind": "video",
    "display_name": "Seedance 2.0",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-08-17",
    "operations": {
        "video.generate": {
            "operation": "video.generate",
            "capabilities": ["video.i2v.first_frame"],
            "output_constraints": {},
            "reference_constraints": {"first_frame": {"min": 1, "max": 1}},
            "exclusive_groups": [],
        }
    },
    "option_schema": {"namespace": "", "options": {}},
}


def upgrade() -> None:
    manifest = _SEEDANCE_2_MANIFEST
    bind = op.get_bind()
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
            "option_schema": json.dumps(manifest["option_schema"]),
            "documented_at": date.fromisoformat(str(manifest["documented_at"])),
            "manifest_hash": _hash_manifest(manifest),
        },
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM provider_model_catalog_entries
        WHERE provider_type = 'volcengine'
          AND protocol_profile = 'ark_cn_v1'
          AND model_id = 'doubao-seedance-2-0-260128'
          AND model_revision = 'v1'
        """
    )
