"""Resolve licensed project-linked media for editing and export."""

from pathlib import Path

from alembic import op

revision = "20261123_0126"
down_revision = "20261120_0125"
branch_labels = None
depends_on = None

_FUNCTION = "app.public_edit_media(uuid, uuid, uuid, uuid, text)"


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2] / "app/assets/sql"
    content = (root / "public_item_content_v1.sql").read_text(encoding="utf-8").format(
        schema="public.", actor="app.current_user_id()", workspace="app.current_workspace_id()",
        active_project="app.current_project_id()", project="p_project", link="p_link",
        publication="NULL::uuid", item="p_item",
        permits_library="r.allowed_uses @> jsonb_build_array('library_reference'::text, p_purpose)",
    )
    query = (root / "public_edit_media_v1.sql").read_text(encoding="utf-8").format(
        content_query=content, schema="public.", item="p_item", publication="p_publication",
        purpose="p_purpose",
    )
    op.execute(
        "CREATE FUNCTION app.public_edit_media(p_project uuid, p_link uuid, p_publication uuid, "
        "p_item uuid, p_purpose text) RETURNS TABLE(id uuid, project_id uuid, "
        "artifact_type varchar, storage_state varchar, content_hash varchar, mime_type varchar, "
        "object_key varchar, byte_size bigint) LANGUAGE sql STABLE SECURITY DEFINER "
        "SET search_path = pg_catalog, pg_temp AS $$ " + query + " $$"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO dramaforge_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
