"""Find due, already-submitted observations in a restored queue without admitting new work."""

from alembic import op

revision = "20261123_0131"
down_revision = "20261123_0130"
branch_labels = None
depends_on = None

_SIG = "app.recovery_only_provider_contexts(integer,text,uuid)"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.recovery_only_provider_contexts(
            p_limit integer,p_commit text,p_after uuid
        ) RETURNS TABLE(node_run_id uuid,owner_user_id uuid,workspace_id uuid,project_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        SELECT nr.id,w.owner_user_id,w.id,p.id FROM public.node_runs nr
           JOIN public.projects p ON p.id=nr.project_id
           JOIN public.workspaces w ON w.id=p.workspace_id
           JOIN LATERAL (
               SELECT po.status,po.provider_operation_id,po.response_summary,po.resume_token
               FROM public.provider_operations po
               WHERE po.node_run_id=nr.id AND po.execution_path_version='unified-v1'
               ORDER BY po.attempt_no DESC,po.created_at DESC LIMIT 1
           ) op ON true
           WHERE nr.status IN ('queued','cancel_requested') AND nr.started_at IS NULL
             AND (nr.next_attempt_at IS NULL OR nr.next_attempt_at<=now())
             AND (p_after IS NULL OR nr.id>p_after)
             AND (p_commit IS NULL OR nr.input_snapshot->>'source_commit'=p_commit)
             AND op.status IN ('submitted','running','timed_out','cancel_requested')
             AND ((op.provider_operation_id IS NOT NULL AND op.resume_token IS NOT NULL)
                  OR op.response_summary #>> '{synchronous_result,schema_version}'='1')
           ORDER BY nr.id LIMIT least(greatest(p_limit,0),50)
        $$
    """)
    op.execute(f"ALTER FUNCTION {_SIG} OWNER TO dramaforge_worker_resolver")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIG} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIG} TO dramaforge,dramaforge_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_SIG}")
