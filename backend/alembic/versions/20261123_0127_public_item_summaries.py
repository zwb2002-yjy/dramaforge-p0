"""Expose only public library card fields across the owner's workspaces."""

from pathlib import Path

from alembic import op

revision = "20261123_0127"
down_revision = "20261123_0126"
branch_labels = None
depends_on = None

_FUNCTION = "app.public_item_summaries(uuid)"


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2] / "app/assets/sql"
    query = (root / "public_item_summaries_v1.sql").read_text(encoding="utf-8").format(
        content_query="SELECT 1 FROM app.public_item_content(pub.id, member.id, NULL, NULL)",
        schema="public.", publication="p_publication", actor="app.current_user_id()",
        workspace="app.current_workspace_id()",
    )
    op.execute(
        "CREATE FUNCTION app.public_item_summaries(p_publication uuid) RETURNS TABLE("
        "id uuid, media_kind varchar, role varchar, mime_type varchar, width integer, "
        "height integer, duration_seconds double precision, preview_available boolean) "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$ "
        + query + " $$"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO dramaforge_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
