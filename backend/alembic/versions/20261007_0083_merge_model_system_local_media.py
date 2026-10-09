"""Merge model-system and local-media migration histories.

Revision ID: 20261007_0083
Revises: 20260929_0077, 20260930_0082
"""

revision: str = "20261007_0083"
down_revision: tuple[str, str] = ("20260929_0077", "20260930_0082")
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
