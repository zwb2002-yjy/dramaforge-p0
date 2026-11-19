"""Explicit work type and project intent, preserving unconfirmed legacy projects."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "20261117_0100"
down_revision = "20261113_0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("work_type", sa.String(32), nullable=True))
    op.add_column(
        "projects", sa.Column("creative_goal", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "projects", sa.Column("audience", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "projects", sa.Column("planned_duration_seconds", sa.Numeric(12, 3), nullable=True),
    )
    op.add_column("projects", sa.Column("planned_episode_count", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_projects_id_workspace", "projects", ["id", "workspace_id"])
    op.create_unique_constraint("uq_workspaces_id_owner", "workspaces", ["id", "owner_user_id"])
    op.create_check_constraint(
        "ck_projects_work_type", "projects",
        "work_type IS NULL OR work_type IN ('animation_promo','single_comic','serial_comic')",
    )
    op.create_check_constraint(
        "ck_projects_creative_goal_length", "projects", "length(creative_goal) <= 16000",
    )
    op.create_check_constraint(
        "ck_projects_audience_length", "projects", "length(audience) <= 2000",
    )
    # A finite upper bound also rejects PostgreSQL numeric NaN, which sorts above numbers.
    op.create_check_constraint(
        "ck_projects_planned_duration", "projects",
        "planned_duration_seconds IS NULL OR "
        "(planned_duration_seconds > 0 AND planned_duration_seconds < 1000000000)",
    )
    op.create_check_constraint(
        "ck_projects_episode_plan", "projects",
        "planned_episode_count IS NULL OR (planned_episode_count > 0 AND "
        "(work_type IS NULL OR "
        "(work_type = 'single_comic' AND planned_episode_count = 1) OR "
        "(work_type = 'serial_comic' AND planned_episode_count >= 2)))",
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("INSTITUTION_INTENT_DOWNGRADE_REQUIRES_ONLINE_PREFLIGHT")
    populated = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM projects WHERE work_type IS NOT NULL "
        "OR creative_goal <> '' OR audience <> '' OR planned_duration_seconds IS NOT NULL "
        "OR planned_episode_count IS NOT NULL) OR "
        "EXISTS (SELECT 1 FROM event_log WHERE event_type = 'project_changed')"
    )).scalar_one()
    if populated:
        raise RuntimeError("INSTITUTION_INTENT_DOWNGRADE_REQUIRES_EMPTY_FIELDS")
    for name in (
        "ck_projects_episode_plan", "ck_projects_planned_duration",
        "ck_projects_audience_length", "ck_projects_creative_goal_length", "ck_projects_work_type",
    ):
        op.drop_constraint(name, "projects", type_="check")
    op.drop_constraint("uq_workspaces_id_owner", "workspaces", type_="unique")
    op.drop_constraint("uq_projects_id_workspace", "projects", type_="unique")
    for name in (
        "planned_episode_count", "planned_duration_seconds", "audience", "creative_goal", "work_type",
    ):
        op.drop_column("projects", name)
