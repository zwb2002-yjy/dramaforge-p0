"""Add the official MiniMax H3 dual-mode video catalog revision.

Revision ID: 20260929_0079
Revises: 20260929_0078
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0079"
down_revision: str | None = "20260929_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MANIFEST: dict[str, object] = {
    "manifest_version": "2026-09-29",
    "provider_type": "minimax",
    "protocol_profile": "minimax_cn_v1",
    "model_id": "MiniMax-H3",
    "model_revision": "v2",
    "media_kind": "video",
    "display_name": "MiniMax H3",
    "lifecycle": "active",
    "catalog_source": "official_static",
    "documented_at": "2026-09-29",
    "operations": {
        "video.generate": {
            "operation": "video.generate",
            "capabilities": ["video.i2v.first_frame", "video.t2v"],
            "output_constraints": {
                "modes": {
                    "first_frame": {
                        "resolution": "768P",
                        "duration_seconds": 5,
                        "aspect_ratio": "adaptive",
                        "native_audio": False,
                    },
                    "text_to_video": {
                        "resolution": "2K",
                        "duration_seconds": 5,
                        "aspect_ratio": {"allowed": ["9:16", "16:9"]},
                        "native_audio": True,
                    },
                },
            },
            "reference_constraints": {"first_frame": {"min": 0, "max": 1}},
            "exclusive_groups": [],
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
               :display_name, :media_kind, 'active', 'official_static',
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
            "documented_at": date(2026, 9, 29),
            "manifest_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE provider_model_catalog_entries SET lifecycle = 'deprecated', updated_at = now()
            WHERE provider_type = 'minimax'
              AND protocol_profile = 'minimax_cn_v1'
              AND model_id = 'MiniMax-H3'
              AND model_revision = 'v2'
            """
        )
    )
