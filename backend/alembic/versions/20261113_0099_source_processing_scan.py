"""Narrow durable source work discovery for the existing background dispatcher."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261113_0099"
down_revision = "20261113_0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_file_revisions",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        "ck_project_file_revision_attempt", "project_file_revisions", "attempt > 0"
    )
    op.create_index(
        "ix_project_file_revision_pending",
        "project_file_revisions",
        ["id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute("""
        CREATE FUNCTION app.pending_project_file_contexts(
            p_limit integer, p_after_revision_id uuid DEFAULT NULL)
        RETURNS TABLE(revision_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid,
                      attempt integer)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
            SELECT r.id, w.owner_user_id, w.id, p.id, r.attempt
            FROM project_file_revisions r
            JOIN project_files f ON f.id = r.file_id AND f.project_id = r.project_id
            JOIN projects p ON p.id = f.project_id
            JOIN workspaces w ON w.id = p.workspace_id
            JOIN users u ON u.id = w.owner_user_id
            WHERE r.status = 'pending' AND f.detached_at IS NULL
              AND p.deleted_at IS NULL AND u.is_active
              AND (p_after_revision_id IS NULL OR r.id > p_after_revision_id)
            ORDER BY r.id
            LIMIT LEAST(GREATEST(p_limit, 0), 100)
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.pending_project_file_contexts(integer, uuid) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pending_project_file_contexts(integer, uuid) TO dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION app.pending_project_file_contexts(integer, uuid)")
    op.drop_index("ix_project_file_revision_pending", table_name="project_file_revisions")
    op.drop_constraint("ck_project_file_revision_attempt", "project_file_revisions", type_="check")
    op.drop_column("project_file_revisions", "attempt")
