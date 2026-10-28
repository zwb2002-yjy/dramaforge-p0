"""Bounded ownership discovery for interrupted local Final Film uploads."""

from alembic import op

revision = "20261028_0090"
down_revision = "20261027_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE FUNCTION app.final_film_upload_contexts(p_limit integer)
        RETURNS TABLE(node_run_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public
        AS $$
            SELECT o.node_run_id FROM public.provider_operations o
            WHERE o.operation_kind = 'final_film.compose'
              AND jsonb_array_length(COALESCE(o.request_summary->'upload_objects', '[]'::jsonb)) > 0
              AND (o.status IN ('succeeded', 'failed', 'cancelled')
                   OR (o.status = 'submission_started'
                       AND o.submitted_at < now() - interval '31 minutes'))
            ORDER BY o.updated_at, o.created_at, o.id
            LIMIT LEAST(GREATEST(p_limit, 0), 50)
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.final_film_upload_contexts(integer) FROM PUBLIC")
    op.execute(
        "ALTER FUNCTION app.final_film_upload_contexts(integer) OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.final_film_upload_contexts(integer) TO dramaforge, dramaforge_app"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION app.final_film_upload_contexts(integer)")
