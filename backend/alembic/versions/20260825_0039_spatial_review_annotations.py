"""Add normalized point and region metadata to review annotations.

Revision ID: 20260825_0039
Revises: 20260825_0038
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0039"
down_revision: str | None = "20260825_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_annotations",
        sa.Column("target_kind", sa.String(24), nullable=False, server_default="shot"),
    )
    op.add_column("review_annotations", sa.Column("x", sa.Numeric(8, 6), nullable=True))
    op.add_column("review_annotations", sa.Column("y", sa.Numeric(8, 6), nullable=True))
    op.add_column("review_annotations", sa.Column("width", sa.Numeric(8, 6), nullable=True))
    op.add_column("review_annotations", sa.Column("height", sa.Numeric(8, 6), nullable=True))
    op.create_check_constraint(
        "ck_review_annotation_target_kind",
        "review_annotations",
        "target_kind IN ('shot', 'video_time', 'image_point', 'image_region')",
    )
    for column in ("x", "y", "width", "height"):
        op.create_check_constraint(
            f"ck_review_annotation_{column}_normalized",
            "review_annotations",
            f"{column} IS NULL OR ({column} >= 0 AND {column} <= 1)",
        )
    op.create_check_constraint(
        "ck_review_annotation_region_x_bounds",
        "review_annotations",
        "x IS NULL OR width IS NULL OR x + width <= 1",
    )
    op.create_check_constraint(
        "ck_review_annotation_region_y_bounds",
        "review_annotations",
        "y IS NULL OR height IS NULL OR y + height <= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_annotation_region_y_bounds", "review_annotations", type_="check"
    )
    op.drop_constraint(
        "ck_review_annotation_region_x_bounds", "review_annotations", type_="check"
    )
    for column in reversed(("x", "y", "width", "height")):
        op.drop_constraint(
            f"ck_review_annotation_{column}_normalized",
            "review_annotations",
            type_="check",
        )
    op.drop_constraint(
        "ck_review_annotation_target_kind", "review_annotations", type_="check"
    )
    for column in reversed(("target_kind", "x", "y", "width", "height")):
        op.drop_column("review_annotations", column)
