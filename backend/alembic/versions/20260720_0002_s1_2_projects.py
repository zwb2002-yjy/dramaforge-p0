"""S1.2 projects, project_members, user_project_preferences.

Revision ID: 20260720_0002
Revises: 20260720_0001
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260720_0002"
down_revision: Union[str, None] = "20260720_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    project_stage = postgresql.ENUM(
        "draft",
        "planning",
        "production",
        "review",
        "delivering",
        "archived",
        name="project_stage",
        create_type=False,
    )
    experience_mode = postgresql.ENUM(
        "quick", "workbench", name="experience_mode", create_type=False
    )
    member_role = postgresql.ENUM(
        "owner",
        "admin",
        "editor",
        "reviewer",
        "viewer",
        name="member_role",
        create_type=False,
    )
    project_stage.create(op.get_bind(), checkfirst=True)
    experience_mode.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("stage", project_stage, server_default="draft", nullable=False),
        sa.Column("aspect_ratio", sa.String(8), nullable=False),
        sa.Column("target_platform", sa.String(40), server_default="general", nullable=False),
        sa.Column("style_bible", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("budget_limit", sa.Numeric(20, 6), nullable=False),
        sa.Column("budget_currency", sa.CHAR(3), server_default="USD", nullable=False),
        sa.Column("provider_dispatch_frozen", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "name", name="uq_projects_org_name"),
        sa.CheckConstraint("aspect_ratio IN ('9:16','16:9')", name="ck_projects_aspect"),
        sa.CheckConstraint("budget_limit >= 0", name="ck_projects_budget"),
        sa.CheckConstraint("version > 0", name="ck_projects_version"),
    )
    op.create_index("idx_projects_org_stage", "projects", ["organization_id", "stage"])
    op.create_table(
        "project_members",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", member_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_table(
        "user_project_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experience_mode", experience_mode, server_default="workbench", nullable=False),
        sa.Column("last_guided_step", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )


def downgrade() -> None:
    op.drop_table("user_project_preferences")
    op.drop_table("project_members")
    op.drop_index("idx_projects_org_stage", table_name="projects")
    op.drop_table("projects")
