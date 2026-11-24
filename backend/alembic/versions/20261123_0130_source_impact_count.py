"""A read-only, Owner-scoped count of impacted uses in other projects."""

from pathlib import Path

from alembic import op

revision = "20261123_0130"
down_revision = "20261123_0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    template = (
        Path(__file__).resolve().parents[2] / "app/assets/sql/source_other_project_impact_v1.sql"
    )
    query = template.read_text(encoding="utf-8").format(
        schema="public.",
        actor="app.current_user_id()",
        workspace="app.current_workspace_id()",
        active_project="app.current_project_id()",
        project="p_project",
        subject="p_subject",
    )
    op.execute(
        "CREATE FUNCTION app.source_other_project_uses(p_project uuid,p_subject uuid) RETURNS bigint "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ "
        + query
        + " $$"
    )
    op.execute("REVOKE ALL ON FUNCTION app.source_other_project_uses(uuid,uuid) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.source_other_project_uses(uuid,uuid) TO dramaforge_app"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION app.source_other_project_uses(uuid,uuid)")
