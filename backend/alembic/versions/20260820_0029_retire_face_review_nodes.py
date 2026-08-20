"""Migrate historical face-review graph nodes to identity review.

Revision ID: 20260820_0029
Revises: 20260819_0028
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_0029"
down_revision: str | None = "20260819_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE graph_nodes
        SET node_type = 'identity_review',
            node_key = CASE
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM graph_nodes current_node
                    WHERE current_node.graph_version_id = graph_nodes.graph_version_id
                      AND current_node.node_key = 'identity_review'
                ) THEN 'identity_review'
                ELSE node_key
            END,
            display_name = 'Identity review'
        WHERE node_type = 'face_review'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260820_0029 is intentionally irreversible; migrated historical graph "
        "nodes must not regain the retired face-review contract"
    )
