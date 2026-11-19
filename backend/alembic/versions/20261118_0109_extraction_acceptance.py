"""Freeze the accepted extraction attempt and its processor contract (I4-01).

The revision row keeps the work receipt (attempt/status) and now also stores the
processor profile the attempt was accepted under. The event log keeps the immutable
acceptance facts (request key/hash, action, accepted attempt, profile) as schema 2,
with partial unique indexes so one request key and one accepted attempt cannot be
recorded twice. Legacy rows keep a NULL profile and need an explicit retry.

Revision ID: 20261118_0109
Revises: 20261118_0108
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_0109"
down_revision: str | None = "20261118_0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACCEPTANCE_WHERE = (
    "event_type = 'project_file.extraction_requested' AND schema_version = 2"
)


def upgrade() -> None:
    op.add_column(
        "project_file_revisions",
        sa.Column("processor_profile_revision", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_project_file_revision_profile",
        "project_file_revisions",
        "processor_profile_revision IS NULL OR length(processor_profile_revision) = 64",
    )
    op.create_index(
        "uq_project_file_acceptance_key",
        "event_log",
        ["project_id", "aggregate_id", sa.text("(payload ->> 'request_key')")],
        unique=True,
        postgresql_where=sa.text(_ACCEPTANCE_WHERE),
    )
    op.create_index(
        "uq_project_file_acceptance_attempt",
        "event_log",
        ["project_id", "aggregate_id", sa.text("(payload ->> 'accepted_attempt')")],
        unique=True,
        postgresql_where=sa.text(_ACCEPTANCE_WHERE),
    )


def downgrade() -> None:
    op.drop_index("uq_project_file_acceptance_attempt", table_name="event_log")
    op.drop_index("uq_project_file_acceptance_key", table_name="event_log")
    op.drop_constraint(
        "ck_project_file_revision_profile",
        "project_file_revisions",
        type_="check",
    )
    op.drop_column("project_file_revisions", "processor_profile_revision")
