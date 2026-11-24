"""D6 media configuration on the project profile row (I8a-01).

Three media defaults (image/video/voice) and voice options live on the existing
project-unique production_model_profiles row. Legacy rows are stamped
media_config_version=1 (read-only until explicitly reconciled); new rows start at 2.
The text-only ``bindings`` JSON keeps planning.* slots and must not carry media keys
at version 2.

Revision ID: 20261118_0119
Revises: 20261118_0118
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261118_0119"
down_revision: str | None = "20261118_0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_provider_model_binding_workspace",
        "provider_model_bindings",
        ["workspace_id", "id"],
    )
    op.add_column(
        "production_model_profiles",
        sa.Column(
            "media_config_version", sa.SmallInteger(), nullable=False, server_default="2"
        ),
    )
    op.add_column(
        "production_model_profiles", sa.Column("image_model_binding_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "production_model_profiles", sa.Column("video_model_binding_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "production_model_profiles", sa.Column("voice_model_binding_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "production_model_profiles",
        sa.Column(
            "voice_options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.execute(
        "UPDATE production_model_profiles SET media_config_version = 1 "
        "WHERE media_config_version = 2"
    )
    op.create_check_constraint(
        "ck_model_profile_media_config_version",
        "production_model_profiles",
        "media_config_version IN (1, 2)",
    )
    op.create_check_constraint(
        "ck_model_profile_workspace_media_empty",
        "production_model_profiles",
        "project_id IS NOT NULL OR (image_model_binding_id IS NULL "
        "AND video_model_binding_id IS NULL AND voice_model_binding_id IS NULL "
        "AND voice_options = '{}'::jsonb)",
    )
    for column, name in (
        ("image_model_binding_id", "fk_model_profile_image_binding"),
        ("video_model_binding_id", "fk_model_profile_video_binding"),
        ("voice_model_binding_id", "fk_model_profile_voice_binding"),
    ):
        op.create_foreign_key(
            name,
            "production_model_profiles",
            "provider_model_bindings",
            ["workspace_id", column],
            ["workspace_id", "id"],
            ondelete="RESTRICT",
        )
        op.create_index(
            f"ix_model_profile_{column}",
            "production_model_profiles",
            [column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )


def downgrade() -> None:
    for column in (
        "image_model_binding_id",
        "video_model_binding_id",
        "voice_model_binding_id",
    ):
        op.drop_index(f"ix_model_profile_{column}", table_name="production_model_profiles")
        op.drop_constraint(
            f"fk_model_profile_{column.replace('_model_binding_id', '')}_binding",
            "production_model_profiles",
            type_="foreignkey",
        )
    op.drop_constraint(
        "ck_model_profile_workspace_media_empty",
        "production_model_profiles",
        type_="check",
    )
    op.drop_constraint(
        "ck_model_profile_media_config_version",
        "production_model_profiles",
        type_="check",
    )
    op.drop_column("production_model_profiles", "voice_options")
    op.drop_column("production_model_profiles", "voice_model_binding_id")
    op.drop_column("production_model_profiles", "video_model_binding_id")
    op.drop_column("production_model_profiles", "image_model_binding_id")
    op.drop_column("production_model_profiles", "media_config_version")
    op.drop_constraint(
        "uq_provider_model_binding_workspace", "provider_model_bindings", type_="unique"
    )
