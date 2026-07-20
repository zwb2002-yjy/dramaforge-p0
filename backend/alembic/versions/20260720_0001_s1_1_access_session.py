"""S1.1 access session: organizations, users, organization_members.

Revision ID: 20260720_0001
Revises:
Create Date: 2026-07-20

Field-faithful to 04_数据定义全集.md for tables owned by S1.1.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    member_role = postgresql.ENUM(
        "owner",
        "admin",
        "editor",
        "reviewer",
        "viewer",
        name="member_role",
        create_type=False,
    )
    member_role.create(op.get_bind(), checkfirst=True)

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.current_user_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
          SELECT NULLIF(current_setting('app.current_user_id', true),'')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.current_organization_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
          SELECT NULLIF(current_setting('app.current_organization_id', true),'')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.current_project_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
          SELECT NULLIF(current_setting('app.current_project_id', true),'')::uuid
        $$
        """
    )

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("version > 0", name="ck_organizations_version_positive"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("version > 0", name="ck_users_version_positive"),
    )
    op.create_table(
        "organization_members",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", member_role, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("organization_members")
    op.drop_table("users")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS member_role")
