"""S1-RLS-0.1: ENABLE RLS + project/org scope policies for shipped tables.

Revision ID: 20260721_0005
Revises: 20260721_0004
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260721_0005"
down_revision: Union[str, None] = "20260721_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables with direct project_id (USING/WITH CHECK = current_project_id)
_PROJECT_TABLES = (
    "project_members",
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

    # projects: organization scope
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS projects_organization_scope ON projects")
    op.execute(
        """
        CREATE POLICY projects_organization_scope ON projects
        FOR ALL
        USING (
          organization_id = app.current_organization_id()
          OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = projects.id
              AND pm.user_id = app.current_user_id()
          )
          OR id = app.current_project_id()
        )
        WITH CHECK (
          organization_id = app.current_organization_id()
          OR organization_id IS NOT NULL
        )
        """
    )

    # organization_members: user sees own memberships in current org
    op.execute("ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organization_members FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS org_members_scope ON organization_members")
    op.execute(
        """
        CREATE POLICY org_members_scope ON organization_members
        FOR ALL
        USING (
          user_id = app.current_user_id()
          OR organization_id = app.current_organization_id()
        )
        WITH CHECK (
          user_id = app.current_user_id()
          OR organization_id = app.current_organization_id()
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
        if table == "event_log":
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
                  AND (
                    project_id = app.current_project_id()
                    OR app.current_project_id() IS NULL
                  )
                )
                WITH CHECK (user_id = app.current_user_id())
                """
            )
        elif table == "project_members":
            op.execute(
                f"""
                CREATE POLICY {table}_project_scope ON {table}
                FOR ALL
                USING (
                  user_id = app.current_user_id()
                  OR project_id = app.current_project_id()
                )
                WITH CHECK (
                  user_id = app.current_user_id()
                  OR project_id = app.current_project_id()
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
                  OR app.current_project_id() IS NULL
                )
                WITH CHECK (
                  project_id = app.current_project_id()
                  OR app.current_project_id() IS NULL
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
        "organization_members",
        "projects",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_project_scope ON {table}")
        if table == "projects":
            op.execute("DROP POLICY IF EXISTS projects_organization_scope ON projects")
        if table == "organization_members":
            op.execute("DROP POLICY IF EXISTS org_members_scope ON organization_members")
        if table == "users":
            op.execute("DROP POLICY IF EXISTS users_self ON users")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
