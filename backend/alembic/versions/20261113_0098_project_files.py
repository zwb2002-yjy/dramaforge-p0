"""Project-private originals, source revisions and local extraction receipts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261113_0098"
down_revision = "20261111_0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_files",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("filename", sa.String(260), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("detached_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("id", "project_id", name="uq_project_file_scope"),
        sa.CheckConstraint("version > 0", name="ck_project_files_version"),
        sa.CheckConstraint("content_version > 0", name="ck_project_files_content_version"),
    )
    op.create_index("ix_project_files_project", "project_files", ["project_id", "created_at"])
    op.create_table(
        "project_file_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(260), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("parser_version", sa.String(80)),
        sa.Column("excerpts", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["file_id", "project_id"], ["project_files.id", "project_files.project_id"],
            name="fk_project_file_revision_scope", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("file_id", "number", name="uq_project_file_revision_number"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_project_file_request"),
        sa.CheckConstraint("number > 0", name="ck_project_file_revision_number"),
        sa.CheckConstraint("byte_size >= 0", name="ck_project_file_revision_size"),
        sa.CheckConstraint("status IN ('pending','parsed','failed')",
                           name="ck_project_file_revision_status"),
    )
    op.create_index("ix_project_file_revision_hash", "project_file_revisions",
                    ["project_id", "content_hash"])
    for table in ("project_files", "project_file_revisions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
                   "USING (project_id = app.current_project_id()) "
                   "WITH CHECK (project_id = app.current_project_id())")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dramaforge_app")


def downgrade() -> None:
    # Original objects are deliberately retained. A populated source history must
    # not be destroyed by an automatic code rollback.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS(SELECT 1 FROM project_files)")).scalar():
        raise RuntimeError("PROJECT_FILES_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE")
    op.drop_table("project_file_revisions")
    op.drop_table("project_files")
