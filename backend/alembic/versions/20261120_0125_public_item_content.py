"""Resolve one owner-scoped public media item against current library-use rights."""

from pathlib import Path

from alembic import op

revision = "20261120_0125"
down_revision = "20261120_0124"
branch_labels = None
depends_on = None

_FUNCTION = "app.public_item_content(uuid, uuid, uuid, uuid)"


def upgrade() -> None:
    template = Path(__file__).resolve().parents[2] / "app/assets/sql/public_item_content_v1.sql"
    query = template.read_text(encoding="utf-8").format(
        schema="public.",
        actor="app.current_user_id()",
        workspace="app.current_workspace_id()",
        active_project="app.current_project_id()",
        project="p_project",
        publication="p_publication",
        link="p_link",
        item="p_item",
        permits_library="""r.allowed_uses @> '["library_reference"]'::jsonb""",
    )
    op.execute(
        "CREATE FUNCTION app.public_item_content(p_publication uuid, p_item uuid, "
        "p_project uuid, p_link uuid) RETURNS TABLE(object_key varchar, mime_type varchar, "
        "byte_size bigint, content_hash varchar) LANGUAGE sql STABLE SECURITY DEFINER "
        "SET search_path = pg_catalog, pg_temp AS $$ " + query + " $$"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO dramaforge_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
