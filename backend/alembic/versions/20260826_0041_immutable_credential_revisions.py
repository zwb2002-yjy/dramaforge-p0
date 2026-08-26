"""Convert BYOK credentials into immutable account revision records.

Revision ID: 20260826_0041
Revises: 20260826_0040
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0041"
down_revision: str | None = "20260826_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREDENTIALS = "encrypted_provider_credentials"
_OLD_UNIQUE = "uq_encrypted_provider_credential"
_REVISION_UNIQUE = "uq_encrypted_provider_credential_revision"
_IDENTITY_UNIQUE = "uq_encrypted_provider_credential_identity"
_SUPERSEDES_FK = "fk_encrypted_provider_credential_supersedes_identity"
_SUPERSEDES_INDEX = "ix_encrypted_provider_credential_supersedes_id"


def upgrade() -> None:
    # The old unique constraint guarantees at most one pre-migration row per
    # workspace/provider, so every retained historical row is a deterministic
    # revision-1 baseline.  Keep a server default as a compatibility bridge for
    # old maintenance/import SQL that omits the new revision columns.
    op.drop_constraint(_OLD_UNIQUE, _CREDENTIALS, type_="unique")
    op.add_column(
        _CREDENTIALS,
        sa.Column("revision_no", sa.Integer(), nullable=True, server_default=sa.text("1")),
    )
    op.add_column(
        _CREDENTIALS,
        sa.Column(
            "supersedes_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            f"UPDATE {_CREDENTIALS} SET revision_no = 1 "
            "WHERE revision_no IS NULL"
        )
    )
    op.alter_column(
        _CREDENTIALS,
        "revision_no",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("1"),
    )
    # Credential rows are immutable account revisions; updated_at would imply
    # an in-place account update and is no longer part of the record contract.
    op.drop_column(_CREDENTIALS, "updated_at")
    op.create_unique_constraint(
        _REVISION_UNIQUE,
        _CREDENTIALS,
        ["workspace_id", "provider", "revision_no"],
    )
    op.create_unique_constraint(
        _IDENTITY_UNIQUE,
        _CREDENTIALS,
        ["id", "workspace_id", "provider"],
    )
    op.create_index(_SUPERSEDES_INDEX, _CREDENTIALS, ["supersedes_id"])
    op.create_foreign_key(
        _SUPERSEDES_FK,
        _CREDENTIALS,
        _CREDENTIALS,
        ["supersedes_id", "workspace_id", "provider"],
        ["id", "workspace_id", "provider"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_encrypted_provider_credential_revision_positive",
        _CREDENTIALS,
        "revision_no > 0",
    )
    op.create_check_constraint(
        "ck_encrypted_provider_credential_not_self_superseding",
        _CREDENTIALS,
        "supersedes_id IS NULL OR supersedes_id <> id",
    )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            f"SELECT 1 FROM {_CREDENTIALS} "
            "GROUP BY workspace_id, provider HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot downgrade immutable credential revisions while historical revisions exist"
        )

    op.drop_constraint(
        "ck_encrypted_provider_credential_not_self_superseding",
        _CREDENTIALS,
        type_="check",
    )
    op.drop_constraint(
        "ck_encrypted_provider_credential_revision_positive",
        _CREDENTIALS,
        type_="check",
    )
    op.drop_constraint(_SUPERSEDES_FK, _CREDENTIALS, type_="foreignkey")
    op.drop_index(_SUPERSEDES_INDEX, table_name=_CREDENTIALS)
    op.drop_constraint(_IDENTITY_UNIQUE, _CREDENTIALS, type_="unique")
    op.drop_constraint(_REVISION_UNIQUE, _CREDENTIALS, type_="unique")
    op.drop_column(_CREDENTIALS, "supersedes_id")
    op.drop_column(_CREDENTIALS, "revision_no")
    op.add_column(
        _CREDENTIALS,
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(_OLD_UNIQUE, _CREDENTIALS, ["workspace_id", "provider"])
