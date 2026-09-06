"""Add professional workspace foundation fields.

Revision ID: 20260826_0043
Revises: 20260826_0042
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0043"
down_revision: str | None = "20260826_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_project_preferences",
        sa.Column(
            "workspace_state",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    op.add_column(
        "scenes",
        sa.Column(
            "design_state",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    op.add_column(
        "shots",
        sa.Column(
            "director_state",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "shots",
        sa.Column(
            "image_prompt",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "shots",
        sa.Column(
            "video_prompt",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "shots",
        sa.Column(
            "formal_keyframe_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "shots",
        sa.Column(
            "formal_video_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "shots",
        sa.Column(
            "formal_composite_artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_shots_formal_keyframe_artifact",
        "shots",
        "artifacts",
        ["formal_keyframe_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_shots_formal_video_artifact",
        "shots",
        "artifacts",
        ["formal_video_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_shots_formal_composite_artifact",
        "shots",
        "artifacts",
        ["formal_composite_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_shots_formal_keyframe_artifact_id",
        "shots",
        ["formal_keyframe_artifact_id"],
    )
    op.create_index(
        "ix_shots_formal_video_artifact_id",
        "shots",
        ["formal_video_artifact_id"],
    )
    op.create_index(
        "ix_shots_formal_composite_artifact_id",
        "shots",
        ["formal_composite_artifact_id"],
    )

    op.add_column(
        "assets",
        sa.Column(
            "current_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_assets_current_version",
        "assets",
        "asset_versions",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_assets_current_version_id",
        "assets",
        ["current_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assets_current_version_id", table_name="assets")
    op.drop_constraint("fk_assets_current_version", "assets", type_="foreignkey")
    op.drop_column("assets", "current_version_id")

    op.drop_index("ix_shots_formal_composite_artifact_id", table_name="shots")
    op.drop_index("ix_shots_formal_video_artifact_id", table_name="shots")
    op.drop_index("ix_shots_formal_keyframe_artifact_id", table_name="shots")
    op.drop_constraint(
        "fk_shots_formal_composite_artifact", "shots", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_shots_formal_video_artifact", "shots", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_shots_formal_keyframe_artifact", "shots", type_="foreignkey"
    )
    op.drop_column("shots", "formal_composite_artifact_id")
    op.drop_column("shots", "formal_video_artifact_id")
    op.drop_column("shots", "formal_keyframe_artifact_id")
    op.drop_column("shots", "video_prompt")
    op.drop_column("shots", "image_prompt")
    op.drop_column("shots", "director_state")

    op.drop_column("scenes", "design_state")
    op.drop_column("user_project_preferences", "workspace_state")
