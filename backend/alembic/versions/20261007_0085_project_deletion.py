"""Remove deleted projects from the workspace while preserving production evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20261007_0085"
down_revision = "20261007_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("uq_projects_workspace_name", "projects", type_="unique")
    op.create_index(
        "uq_projects_workspace_name",
        "projects",
        ["workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Reusing a deleted project's name can make the prior unique constraint invalid.
    raise RuntimeError("Project deletion is irreversible; restore a database snapshot to downgrade")
