"""Narrow project-linked visual inputs with a current source permission fingerprint."""

from pathlib import Path

from alembic import op

revision = "20261123_0128"
down_revision = "20261123_0127"
branch_labels = None
depends_on = None

_FUNCTION = "app.public_vision_source(uuid, uuid, uuid, boolean, boolean)"


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2] / "app/assets/sql"
    template = (root / "public_vision_v1.sql").read_text(encoding="utf-8")
    common = dict(
        schema="public.", project="p_project", link="p_link", item="p_item", preview="p_preview",
        permitted="SELECT 1 FROM app.public_item_content(NULL, p_item, p_project, p_link)",
        external_use="""r.allowed_uses @> '["external_processing"]'::jsonb""",
        revision_key="SELECT encode(sha256(convert_to(string_agg(revision_id::text, ',' "
                     "ORDER BY revision_id), 'UTF8')), 'hex') FROM grants",
    )
    read = template.format(**common, row_lock="", lock_ctes="", lock_check="")
    # Source declaration and lineage writers lock their respective project before writing.
    # The service re-reads the fingerprint after acquiring these locks, before submission.
    locked = template.format(
        **common, row_lock="FOR SHARE OF l,p,a,v",
        lock_ctes=""", locked_projects AS MATERIALIZED (
            SELECT p.id FROM public.projects p WHERE p.id IN (
              SELECT project_id FROM grants UNION
              SELECT a.project_id FROM bounded b JOIN public.artifacts a ON a.id=b.id)
            ORDER BY p.id FOR SHARE OF p)""",
        lock_check="AND (SELECT count(*) FROM locked_projects) > 0",
    )
    op.execute(
        "CREATE FUNCTION app.public_vision_source(p_project uuid, p_link uuid, p_item uuid, "
        "p_preview boolean, p_lock boolean) RETURNS TABLE(id uuid, project_id uuid, "
        "artifact_type varchar, storage_state varchar, object_key text, mime_type varchar, "
        "byte_size bigint, content_hash varchar, publication_revision integer, link_version integer, "
        "revision_key text) LANGUAGE plpgsql VOLATILE SECURITY DEFINER "
        "SET search_path = pg_catalog, pg_temp AS $$ #variable_conflict use_column\n"
        f"BEGIN IF p_lock THEN RETURN QUERY {locked}; ELSE RETURN QUERY {read}; END IF; END $$"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO dramaforge_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
