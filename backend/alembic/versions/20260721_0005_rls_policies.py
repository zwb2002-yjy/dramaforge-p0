"""S1-RLS-0.1: ENABLE RLS + private workspace/project scope policies.

Revision ID: 20260721_0005
Revises: 20260721_0004
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260721_0005"
down_revision: str | None = "20260721_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables with direct project_id (USING/WITH CHECK = current_project_id)
_PROJECT_TABLES = (
    "user_project_preferences",
    "creative_briefs",
    "creative_brief_revisions",
    "creation_plans",
    "planning_authorizations",
    "agent_runs",
    "materialization_operations",
    "artifacts",
    "production_graphs",
    "node_runs",
    "event_log",
    "outbox_events",
)


def upgrade() -> None:
    # Non-owner app role for RLS enforcement tests / production pattern.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dramaforge_app') THEN
            CREATE ROLE dramaforge_app NOINHERIT LOGIN PASSWORD 'dramaforge_app';
          END IF;
        END $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_roles WHERE rolname = 'dramaforge_worker_resolver'
          ) THEN
            CREATE ROLE dramaforge_worker_resolver NOLOGIN NOINHERIT BYPASSRLS;
          END IF;
        END $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO dramaforge_app")
    op.execute("GRANT USAGE ON SCHEMA app TO dramaforge_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dramaforge_app"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dramaforge_app"
    )
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO dramaforge_app")
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dramaforge_app
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.project_id_for_graph_version(p_id uuid)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT g.project_id
          FROM graph_versions gv
          JOIN production_graphs g ON g.id = gv.graph_id
          WHERE gv.id = p_id
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.project_id_for_graph_node(p_id uuid)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT app.project_id_for_graph_version(gn.graph_version_id)
          FROM graph_nodes gn WHERE gn.id = p_id
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.project_id_for_provider_operation(p_id uuid)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT COALESCE(
            (SELECT nr.project_id FROM provider_operations po
               JOIN node_runs nr ON nr.id = po.node_run_id
             WHERE po.id = p_id AND po.node_run_id IS NOT NULL),
            (SELECT ar.project_id FROM provider_operations po
               JOIN agent_runs ar ON ar.id = po.agent_run_id
             WHERE po.id = p_id AND po.agent_run_id IS NOT NULL)
          )
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.node_run_context(p_node_run_id uuid)
        RETURNS TABLE(owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT w.owner_user_id, w.id, p.id
          FROM node_runs nr
          JOIN projects p ON p.id = nr.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE nr.id = p_node_run_id
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.queued_node_run_contexts(
          p_limit integer,
          p_project_id uuid DEFAULT NULL
        )
        RETURNS TABLE(node_run_id uuid, owner_user_id uuid, workspace_id uuid, project_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT nr.id, w.owner_user_id, w.id, p.id
          FROM node_runs nr
          JOIN projects p ON p.id = nr.project_id
          JOIN workspaces w ON w.id = p.workspace_id
          WHERE nr.status = 'queued'
            AND (p_project_id IS NULL OR nr.project_id = p_project_id)
          ORDER BY nr.created_at, nr.id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.pending_outbox_event_contexts(
          p_limit integer,
          p_project_id uuid DEFAULT NULL
        )
        RETURNS TABLE(
          outbox_event_id uuid,
          owner_user_id uuid,
          workspace_id uuid,
          project_id uuid
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT oe.event_id, w.owner_user_id, w.id, p.id
          FROM outbox_events oe
          LEFT JOIN projects p ON p.id = oe.project_id
          LEFT JOIN workspaces w ON w.id = p.workspace_id
          WHERE (
            (oe.status = 'pending' AND oe.next_attempt_at <= now())
            OR (oe.status = 'leased' AND oe.leased_until < now())
          )
            AND (p_project_id IS NULL OR oe.project_id = p_project_id)
          ORDER BY oe.created_at, oe.event_id
          LIMIT GREATEST(p_limit, 0)
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION app.node_run_context(uuid) OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "ALTER FUNCTION app.queued_node_run_contexts(integer, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute(
        "ALTER FUNCTION app.pending_outbox_event_contexts(integer, uuid) "
        "OWNER TO dramaforge_worker_resolver"
    )
    op.execute("REVOKE ALL ON FUNCTION app.node_run_context(uuid) FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION app.queued_node_run_contexts(integer, uuid) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.pending_outbox_event_contexts(integer, uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.node_run_context(uuid) "
        "TO dramaforge, dramaforge_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.queued_node_run_contexts(integer, uuid) "
        "TO dramaforge, dramaforge_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.pending_outbox_event_contexts(integer, uuid) "
        "TO dramaforge, dramaforge_app"
    )
    op.execute(
        "GRANT SELECT ON node_runs, outbox_events, projects, workspaces "
        "TO dramaforge_worker_resolver"
    )

    # Workspaces are visible and mutable only to their owning user.
    op.execute("ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workspaces FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS workspaces_owner_scope ON workspaces")
    op.execute(
        """
        CREATE POLICY workspaces_owner_scope ON workspaces
        FOR ALL
        USING (owner_user_id = app.current_user_id())
        WITH CHECK (owner_user_id = app.current_user_id())
        """
    )

    # Projects must belong to a workspace owned by the current user.
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS projects_workspace_scope ON projects")
    op.execute(
        """
        CREATE POLICY projects_workspace_scope ON projects
        FOR ALL
        USING (
          EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = projects.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
          AND (
            app.current_workspace_id() IS NULL
            OR projects.workspace_id = app.current_workspace_id()
          )
          AND (
            app.current_project_id() IS NULL
            OR projects.id = app.current_project_id()
          )
        )
        WITH CHECK (
          EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = projects.workspace_id
              AND w.owner_user_id = app.current_user_id()
          )
          AND (
            app.current_workspace_id() IS NULL
            OR projects.workspace_id = app.current_workspace_id()
          )
          AND (
            app.current_project_id() IS NULL
            OR projects.id = app.current_project_id()
          )
        )
        """
    )

    # users: self only (INSERT allowed for registration under app role)
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS users_self ON users")
    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute(
        """
        CREATE POLICY users_self ON users
        FOR SELECT
        USING (id = app.current_user_id())
        """
    )
    op.execute(
        """
        CREATE POLICY users_insert ON users
        FOR INSERT
        WITH CHECK (true)
        """
    )
    op.execute(
        """
        CREATE POLICY users_update ON users
        FOR UPDATE
        USING (id = app.current_user_id())
        WITH CHECK (id = app.current_user_id())
        """
    )

    for table in _PROJECT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        # event_log.project_id is nullable — allow NULL only when no project context needed
        if table in {"event_log", "outbox_events"}:
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope ON {table}
                FOR ALL
                USING (
                  project_id IS NULL
                  OR project_id = app.current_project_id()
                )
                WITH CHECK (
                  project_id IS NULL
                  OR project_id = app.current_project_id()
                )
                """
            )
        elif table == "user_project_preferences":
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope ON {table}
                FOR ALL
                USING (
                  user_id = app.current_user_id()
                  AND project_id = app.current_project_id()
                )
                WITH CHECK (
                  user_id = app.current_user_id()
                  AND project_id = app.current_project_id()
                )
                """
            )
        else:
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope ON {table}
                FOR ALL
                USING (
                  project_id = app.current_project_id()
                )
                WITH CHECK (
                  project_id = app.current_project_id()
                )
                """
            )

    # graph_versions / graph_nodes / graph_edges via graph → project
    for table, expr in (
        (
            "graph_versions",
            "app.project_id_for_graph_version(id) = app.current_project_id()",
        ),
        (
            "graph_nodes",
            "app.project_id_for_graph_node(id) = app.current_project_id()",
        ),
        (
            "graph_edges",
            "app.project_id_for_graph_version(graph_version_id) = app.current_project_id()",
        ),
        (
            "provider_operations",
            "app.project_id_for_provider_operation(id) = app.current_project_id()",
        ),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        # INSERT on graph_versions: check via graph_id join
        if table == "graph_versions":
            op.execute(
                """
                CREATE POLICY graph_versions_project_scope ON graph_versions
                FOR ALL
                USING (app.project_id_for_graph_version(id) = app.current_project_id()
                       OR EXISTS (
                         SELECT 1 FROM production_graphs g
                         WHERE g.id = graph_versions.graph_id
                           AND g.project_id = app.current_project_id()
                       ))
                WITH CHECK (EXISTS (
                  SELECT 1 FROM production_graphs g
                  WHERE g.id = graph_versions.graph_id
                    AND g.project_id = app.current_project_id()
                ))
                """
            )
        elif table == "graph_nodes":
            op.execute(
                """
                CREATE POLICY graph_nodes_project_scope ON graph_nodes
                FOR ALL
                USING (
                  app.project_id_for_graph_version(graph_version_id) = app.current_project_id()
                )
                WITH CHECK (
                  app.project_id_for_graph_version(graph_version_id) = app.current_project_id()
                )
                """
            )
        elif table == "graph_edges":
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope ON {table}
                FOR ALL
                USING ({expr})
                WITH CHECK (
                  app.project_id_for_graph_version(graph_version_id) = app.current_project_id()
                )
                """
            )
        else:
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope ON {table}
                FOR ALL
                USING (
                  (node_run_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM node_runs nr WHERE nr.id = provider_operations.node_run_id
                      AND nr.project_id = app.current_project_id()
                  ))
                  OR (agent_run_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM agent_runs ar WHERE ar.id = provider_operations.agent_run_id
                      AND ar.project_id = app.current_project_id()
                  ))
                )
                WITH CHECK (
                  (node_run_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM node_runs nr WHERE nr.id = provider_operations.node_run_id
                      AND nr.project_id = app.current_project_id()
                  ))
                  OR (agent_run_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM agent_runs ar WHERE ar.id = provider_operations.agent_run_id
                      AND ar.project_id = app.current_project_id()
                  ))
                )
                """
            )

    op.execute("ALTER TABLE outbox_dead_letters ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbox_dead_letters FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS outbox_dead_letters_project_scope ON outbox_dead_letters")
    op.execute(
        """
        CREATE POLICY outbox_dead_letters_project_scope ON outbox_dead_letters
        FOR ALL
        USING (
          project_id IS NULL OR project_id = app.current_project_id()
        )
        WITH CHECK (
          project_id IS NULL OR project_id = app.current_project_id()
        )
        """
    )


def downgrade() -> None:
    for table in (
        "outbox_dead_letters",
        "provider_operations",
        "graph_edges",
        "graph_nodes",
        "graph_versions",
        *_PROJECT_TABLES,
        "users",
        "workspaces",
        "projects",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        if table == "projects":
            op.execute("DROP POLICY IF EXISTS projects_workspace_scope ON projects")
        if table == "workspaces":
            op.execute("DROP POLICY IF EXISTS workspaces_owner_scope ON workspaces")
        if table == "users":
            op.execute("DROP POLICY IF EXISTS users_self ON users")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
