"""Freeze public render source grants and validate the immutable output dependency."""

from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261123_0129"
down_revision = "20261123_0128"
branch_labels = None
depends_on = None

_GRANT = "app.public_render_grant(uuid,uuid,uuid,uuid,uuid,text,text)"


# Keep predecessor ACLs private behind the same callable public identities.
_READS = (
    (
        "public_item_content",
        "uuid,uuid,uuid,uuid",
        "p_publication uuid,p_item uuid,p_project uuid,p_link uuid",
        "object_key varchar,mime_type varchar,byte_size bigint,content_hash varchar",
        "p_publication,p_item,p_project,p_link",
        "(SELECT i.artifact_id FROM public.public_asset_publication_items i WHERE i.id=p_item)",
    ),
    (
        "public_edit_media",
        "uuid,uuid,uuid,uuid,text",
        "p_project uuid,p_link uuid,p_publication uuid,p_item uuid,p_purpose text",
        "id uuid,project_id uuid,artifact_type varchar,storage_state varchar,content_hash varchar,"
        "mime_type varchar,object_key varchar,byte_size bigint",
        "p_project,p_link,p_publication,p_item,p_purpose",
        "m.id",
    ),
    (
        "artifact_reference_for_token",
        "text",
        "p_token_hash text",
        "artifact_id uuid,project_id uuid,object_key text,mime_type varchar,content_hash varchar,"
        "expires_at timestamptz,publication_id uuid,publication_item_id uuid,public_asset_link_id uuid",
        "p_token_hash",
        "m.artifact_id",
    ),
)


def _install_read_guards() -> None:
    template = Path(__file__).resolve().parents[2] / "app/assets/sql/render_lineage_v1.sql"
    query = template.read_text(encoding="utf-8").format(
        root="p_root",
        schema="public.",
        length="jsonb_array_length",
        json_type="jsonb_typeof",
        library_allowed="""r.allowed_uses @> '["library_reference"]'::jsonb""",
    )
    op.execute(
        "CREATE FUNCTION app.render_origins_current(p_root uuid) RETURNS boolean "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ "
        + query
        + " $$"
    )
    op.execute("REVOKE ALL ON FUNCTION app.render_origins_current(uuid) FROM PUBLIC")
    op.execute("""CREATE FUNCTION app.project_render_origins(p_project uuid,p_artifact uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        SELECT EXISTS(SELECT 1 FROM public.artifacts a JOIN public.projects p ON p.id=a.project_id
          JOIN public.workspaces w ON w.id=p.workspace_id
          WHERE a.id=p_artifact AND a.project_id=p_project AND p_project=app.current_project_id()
            AND w.owner_user_id=app.current_user_id() AND w.id=app.current_workspace_id()
            AND app.render_origins_current(a.id))
        $$""")
    op.execute("REVOKE ALL ON FUNCTION app.project_render_origins(uuid,uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.project_render_origins(uuid,uuid) TO dramaforge_app")
    for name, types, params, result, args, root in _READS:
        old = f"pre0129_{name}"
        op.execute(f"ALTER FUNCTION app.{name}({types}) RENAME TO {old}")
        op.execute(f"REVOKE EXECUTE ON FUNCTION app.{old}({types}) FROM dramaforge,dramaforge_app")
        op.execute(
            f"CREATE FUNCTION app.{name}({params}) RETURNS TABLE({result}) "
            f"LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ "
            f"SELECT m.* FROM app.{old}({args}) m WHERE app.render_origins_current({root}) $$"
        )
        op.execute(f"REVOKE ALL ON FUNCTION app.{name}({types}) FROM PUBLIC")
        roles = "dramaforge,dramaforge_app" if name == "artifact_reference_for_token" else "dramaforge_app"
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{name}({types}) TO {roles}")


def upgrade() -> None:
    op.add_column(
        "artifact_source_uses",
        sa.Column("access_basis", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    _install_read_guards()
    op.execute("""
        CREATE FUNCTION app.public_render_grant(p_project uuid,p_link uuid,p_publication uuid,
            p_item uuid,p_artifact uuid,p_hash text,p_kind text)
        RETURNS TABLE(source_project_id uuid,source_subject_id uuid,source_revision_id uuid)
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        BEGIN
          IF p_project IS DISTINCT FROM app.current_project_id()
             OR NOT EXISTS (SELECT 1 FROM app.public_edit_media(p_project,p_link,p_publication,p_item,'export') m
               WHERE m.id=p_artifact AND m.content_hash=p_hash AND m.artifact_type=p_kind)
          THEN RETURN; END IF;
          -- Serialise declaration changes, link detach, withdrawal and soft deletion.
          -- Re-read eligibility after locks using a fresh statement snapshot.
          PERFORM owner_project.id FROM public.projects owner_project
          WHERE owner_project.id IN (
            WITH RECURSIVE parents(id) AS (
                SELECT p_artifact UNION SELECT ss.artifact_id FROM parents
                JOIN public.artifact_source_uses edge ON edge.artifact_id=parents.id
                JOIN public.source_use_subjects ss ON ss.id=edge.source_subject_id
                WHERE ss.artifact_id IS NOT NULL
            )
            SELECT a.project_id FROM parents JOIN public.artifacts a ON a.id=parents.id
            UNION SELECT u.source_project_id FROM parents JOIN public.artifact_source_uses u ON u.artifact_id=parents.id
          ) ORDER BY owner_project.id FOR SHARE OF owner_project;
          PERFORM a.id FROM public.artifacts a
          JOIN public.projects p ON a.project_id=p.id
          JOIN public.public_asset_publications pub ON pub.id=p_publication AND pub.source_project_id=p.id
          JOIN public.asset_versions v ON v.id=pub.source_asset_version_id
          JOIN public.project_public_asset_links l ON l.id=p_link AND l.publication_id=pub.id
          WHERE a.id=p_artifact
          FOR SHARE OF a,pub,v,l;
          RETURN QUERY
            SELECT s.project_id,s.id,r.id FROM app.public_edit_media(p_project,p_link,p_publication,p_item,'export') m
            JOIN public.source_use_subjects s ON s.artifact_id=m.id AND s.project_id=m.project_id
            JOIN public.source_use_revisions r ON r.id=s.current_revision_id AND r.subject_id=s.id
            WHERE m.id=p_artifact AND m.content_hash=p_hash AND m.artifact_type=p_kind
              AND r.state='declared' AND r.allowed_uses @> '["library_reference","export"]'::jsonb;
        END $$""")
    op.execute(f"REVOKE ALL ON FUNCTION {_GRANT} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_GRANT} TO dramaforge_app")
    op.execute("""
        CREATE FUNCTION app.validate_public_render_provenance() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        BEGIN
          IF NEW.source_access_kind='private' THEN
            IF NEW.access_basis <> '{}'::jsonb OR NEW.project_id<>NEW.source_project_id THEN
              RAISE EXCEPTION 'SOURCE_USE_SCOPE_INVALID'; END IF;
            RETURN NEW;
          END IF;
          IF NEW.source_access_kind<>'public_asset' OR NOT EXISTS (
            SELECT 1 FROM public.node_runs n
            JOIN public.artifacts output ON output.id=NEW.artifact_id
              AND output.project_id=n.project_id AND output.produced_by_run_id=n.id
            JOIN public.source_use_subjects s ON s.id=NEW.source_subject_id AND s.project_id=NEW.source_project_id
            JOIN public.project_public_asset_links l ON l.id=(NEW.access_basis->>'public_asset_link_id')::uuid
              AND l.project_id=n.project_id
            JOIN public.public_asset_publications p ON p.id=l.publication_id AND p.owner_user_id=l.owner_user_id
              AND p.source_project_id=s.project_id AND p.source_asset_version_id=l.source_asset_version_id
            JOIN public.public_asset_publication_items i ON i.publication_id=p.id AND i.artifact_id=s.artifact_id
              AND i.id=(NEW.access_basis->>'publication_item_id')::uuid AND i.source_project_id=s.project_id
            CROSS JOIN LATERAL jsonb_array_elements(n.input_snapshot->'public_source_grants') g
            WHERE n.id=NEW.consumer_node_run_id AND n.project_id=NEW.project_id
              AND NEW.access_basis=jsonb_build_object('public_asset_link_id',l.id,'publication_id',p.id,
                         'publication_item_id',i.id,'source_artifact_id',s.artifact_id)
              AND g->'access_basis'=NEW.access_basis AND g->>'source_subject_id'=s.id::text
              AND g->>'source_project_id'=s.project_id::text AND g->>'source_revision_id'=NEW.source_revision_id::text
              AND NEW.input_role=concat(g->>'media_kind',':',g->>'clip_index')
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(n.input_snapshot->'public_inputs') inp
                WHERE inp->>'artifact_id'=s.artifact_id::text AND inp->>'artifact_hash'=g->>'artifact_hash'
                  AND inp->>'media_kind'=g->>'media_kind' AND inp->>'clip_index'=g->>'clip_index'
                  AND inp->'source'->>'kind'='public_material' AND inp->'source'->>'public_asset_link_id'=l.id::text
                  AND inp->'source'->>'publication_id'=p.id::text AND inp->'source'->>'publication_item_id'=i.id::text)
          ) THEN RAISE EXCEPTION 'SOURCE_USE_BASIS_INVALID'; END IF;
          RETURN NEW;
        END $$""")
    op.execute("REVOKE ALL ON FUNCTION app.validate_public_render_provenance() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER validate_public_render_provenance BEFORE INSERT ON artifact_source_uses "
        "FOR EACH ROW EXECUTE FUNCTION app.validate_public_render_provenance()"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM artifact_source_uses WHERE access_basis<>'{}'::jsonb)")
    ):
        raise RuntimeError("PUBLIC_SOURCE_EVIDENCE_REQUIRES_ARCHIVE")
    op.execute("DROP TRIGGER validate_public_render_provenance ON artifact_source_uses")
    op.execute("DROP FUNCTION app.validate_public_render_provenance()")
    op.execute(f"DROP FUNCTION {_GRANT}")
    for name, types, *_ in reversed(_READS):
        op.execute(f"DROP FUNCTION app.{name}({types})")
        op.execute(f"ALTER FUNCTION app.pre0129_{name}({types}) RENAME TO {name}")
        roles = "dramaforge,dramaforge_app" if name == "artifact_reference_for_token" else "dramaforge_app"
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{name}({types}) TO {roles}")
    op.execute("DROP FUNCTION app.project_render_origins(uuid,uuid)")
    op.execute("DROP FUNCTION app.render_origins_current(uuid)")
    op.drop_column("artifact_source_uses", "access_basis")
