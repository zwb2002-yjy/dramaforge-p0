"""Source-use subjects, immutable declarations and artifact provenance (M03 part 2).

Declarations and revocation are append-only; the subject keeps a forward pointer
and version. Artifact provenance rows freeze which declaration revision a produced
artifact consumed, so a later revocation cannot rewrite the past.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20261117_0104"
down_revision = "20261117_0103"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_project_scope ON {table} FOR ALL "
        "USING (project_id = app.current_project_id()) "
        "WITH CHECK (project_id = app.current_project_id())"
    )


def _append_only(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT ON {table} TO dramaforge_app")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM dramaforge_app")


def upgrade() -> None:
    op.create_table(
        "source_use_subjects",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("file_revision_id", sa.UUID()),
        sa.Column("artifact_id", sa.UUID()),
        sa.Column("current_revision_id", sa.UUID()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("id", "project_id", name="uq_source_subject_scope"),
        sa.CheckConstraint(
            "(file_revision_id IS NULL) <> (artifact_id IS NULL)",
            name="ck_source_subject_one_source",
        ),
        sa.CheckConstraint("version > 0", name="ck_source_subject_version"),
    )
    op.create_index(
        "ix_source_subject_project", "source_use_subjects", ["project_id", "created_at", "id"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_source_subject_file ON source_use_subjects(file_revision_id) "
        "WHERE file_revision_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_source_subject_artifact ON source_use_subjects(artifact_id) "
        "WHERE artifact_id IS NOT NULL"
    )

    op.create_table(
        "source_use_revisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("origin_expected_version", sa.Integer(), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("allowed_uses", postgresql.JSONB(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["subject_id", "project_id"],
            ["source_use_subjects.id", "source_use_subjects.project_id"],
            name="fk_source_use_revision_subject", ondelete="RESTRICT",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint("subject_id", "number", name="uq_source_use_revision"),
        sa.UniqueConstraint("subject_id", "origin_expected_version", name="uq_source_use_origin"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_source_use_request"),
        sa.UniqueConstraint("id", "subject_id", "project_id", name="uq_source_use_revision_scope"),
        sa.CheckConstraint("number > 0", name="ck_source_use_revision_number"),
        sa.CheckConstraint("origin_expected_version > 0", name="ck_source_use_origin_version"),
        sa.CheckConstraint(
            "result_version = origin_expected_version + 1", name="ck_source_use_result_version",
        ),
        sa.CheckConstraint(
            "state IN ('unreviewed','declared','revoked')", name="ck_source_use_state",
        ),
    )
    op.create_index(
        "ix_source_use_revision_subject", "source_use_revisions",
        ["project_id", "subject_id", "number"],
    )

    op.create_table(
        "artifact_source_uses",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("source_subject_id", sa.UUID(), nullable=False),
        sa.Column("source_project_id", sa.UUID(), nullable=False),
        sa.Column("source_revision_id", sa.UUID(), nullable=False),
        sa.Column("consumer_node_run_id", sa.UUID(), nullable=False),
        sa.Column("input_role", sa.String(40), nullable=False),
        sa.Column("source_access_kind", sa.String(24), nullable=False, server_default="private"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["source_revision_id", "source_subject_id", "source_project_id"],
            [
                "source_use_revisions.id",
                "source_use_revisions.subject_id",
                "source_use_revisions.project_id",
            ],
            name="fk_artifact_source_use_revision", ondelete="RESTRICT",
            deferrable=True, initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "artifact_id", "source_subject_id", "input_role", name="uq_artifact_source_use",
        ),
        sa.CheckConstraint(
            "source_access_kind IN ('private','public_asset','published_knowledge')",
            name="ck_artifact_source_access_kind",
        ),
    )
    op.create_index(
        "ix_artifact_source_use_project", "artifact_source_uses", ["project_id", "artifact_id"],
    )

    for table in ("source_use_subjects", "source_use_revisions", "artifact_source_uses"):
        _rls(table)
    # Subjects carry the forward pointer (UPDATE allowed); revisions/provenance are
    # append-only.
    op.execute("GRANT SELECT, INSERT, UPDATE ON source_use_subjects TO dramaforge_app")
    op.execute("REVOKE DELETE, TRUNCATE ON source_use_subjects FROM dramaforge_app")
    _append_only("source_use_revisions")
    _append_only("artifact_source_uses")


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("SOURCE_USE_DOWNGRADE_REQUIRES_ONLINE_PREFLIGHT")
    connection = op.get_bind()
    populated = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM source_use_subjects) "
            "OR EXISTS(SELECT 1 FROM source_use_revisions)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError("SOURCE_USE_REQUIRE_ARCHIVE_BEFORE_DOWNGRADE")
    for table in ("source_use_subjects", "source_use_revisions", "artifact_source_uses"):
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM dramaforge_app")
    op.drop_index("ix_artifact_source_use_project", table_name="artifact_source_uses")
    op.drop_table("artifact_source_uses")
    op.drop_index("ix_source_use_revision_subject", table_name="source_use_revisions")
    op.drop_table("source_use_revisions")
    op.execute("DROP INDEX IF EXISTS uq_source_subject_file")
    op.execute("DROP INDEX IF EXISTS uq_source_subject_artifact")
    op.drop_index("ix_source_subject_project", table_name="source_use_subjects")
    op.drop_table("source_use_subjects")
