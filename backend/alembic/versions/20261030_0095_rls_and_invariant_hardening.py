"""Harden RLS ownership, missing foreign keys, and retired overloads.

Revision ID: 20261030_0095
Revises: 20261030_0094

The audit found four database-level weaknesses that application code alone
cannot guarantee:

* ``shot_human_locks.shot_id`` had no foreign key, so deleting a Shot orphaned
  its lock row.
* ``exports.episode_id`` had no foreign key.
* the provider availability tables used a workspace-only RLS predicate that did
  not verify workspace ownership, and ``asset_tag_links`` checked only the tag
  side of the junction.
* the retired 2-argument ``app.resumable_provider_node_run_contexts`` overload
  survived beside the current 4-argument function.

It also restores least privilege on the two global/singleton tables and closes
the NULL-project duplicate hole for workspace-level model profiles.
"""

from __future__ import annotations

from alembic import op

revision: str = "20261030_0095"
down_revision: str | None = "20261030_0094"
branch_labels = None
depends_on = None

_AVAILABILITY_TABLES = (
    "provider_availability_evidence",
    "provider_model_availability",
)

_OWNER_PREDICATE = """
    {table}.workspace_id = app.current_workspace_id()
    AND EXISTS (
        SELECT 1 FROM workspaces w
        WHERE w.id = {table}.workspace_id
          AND w.owner_user_id = app.current_user_id()
    )
"""


def _replace_owner_scoped_policy(table: str) -> None:
    predicate = _OWNER_PREDICATE.format(table=table)
    op.execute(f"DROP POLICY IF EXISTS {table}_workspace_scope ON {table}")
    op.execute(
        f"""
        CREATE POLICY {table}_workspace_scope ON {table}
        FOR ALL
        USING ({predicate})
        WITH CHECK ({predicate})
        """
    )


def _replace_workspace_only_policy(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_workspace_scope ON {table}")
    op.execute(
        f"""
        CREATE POLICY {table}_workspace_scope ON {table}
        FOR ALL
        USING (workspace_id = app.current_workspace_id())
        WITH CHECK (workspace_id = app.current_workspace_id())
        """
    )


def upgrade() -> None:
    # --- foreign keys -------------------------------------------------------
    op.execute(
        """
        DELETE FROM shot_human_locks l
        WHERE NOT EXISTS (SELECT 1 FROM shots s WHERE s.id = l.shot_id)
        """
    )
    op.execute(
        """
        ALTER TABLE shot_human_locks
        ADD CONSTRAINT fk_shot_human_locks_shot
        FOREIGN KEY (shot_id) REFERENCES shots (id) ON DELETE CASCADE
        """
    )
    op.execute(
        """
        UPDATE exports e SET episode_id = NULL
        WHERE e.episode_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM episodes ep WHERE ep.id = e.episode_id)
        """
    )
    op.execute(
        """
        ALTER TABLE exports
        ADD CONSTRAINT fk_exports_episode
        FOREIGN KEY (episode_id) REFERENCES episodes (id) ON DELETE SET NULL
        """
    )

    # --- RLS ownership ------------------------------------------------------
    for table in _AVAILABILITY_TABLES:
        _replace_owner_scoped_policy(table)
    op.execute("DROP POLICY IF EXISTS asset_tag_links_project_scope ON asset_tag_links")
    op.execute(
        """
        CREATE POLICY asset_tag_links_project_scope ON asset_tag_links
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM asset_tags t
                WHERE t.id = asset_tag_links.tag_id
                  AND t.project_id = app.current_project_id()
            )
            AND EXISTS (
                SELECT 1 FROM assets a
                WHERE a.id = asset_tag_links.asset_id
                  AND a.project_id = app.current_project_id()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM asset_tags t
                WHERE t.id = asset_tag_links.tag_id
                  AND t.project_id = app.current_project_id()
            )
            AND EXISTS (
                SELECT 1 FROM assets a
                WHERE a.id = asset_tag_links.asset_id
                  AND a.project_id = app.current_project_id()
            )
        )
        """
    )

    # --- retired overload / least privilege / NULL-project uniqueness -------
    op.execute(
        "DROP FUNCTION IF EXISTS app.resumable_provider_node_run_contexts(integer, text)"
    )
    for table in ("key_rotation_audits", "instance_bootstrap_state"):
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM dramaforge_app")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_model_profile_workspace_name_null_project
        ON production_model_profiles (workspace_id, name)
        WHERE project_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_model_profile_workspace_name_null_project")
    for table in ("key_rotation_audits", "instance_bootstrap_state"):
        op.execute(f"GRANT UPDATE, DELETE ON {table} TO dramaforge_app")

    op.execute("DROP POLICY IF EXISTS asset_tag_links_project_scope ON asset_tag_links")
    op.execute(
        """
        CREATE POLICY asset_tag_links_project_scope ON asset_tag_links
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM asset_tags t
                WHERE t.id = asset_tag_links.tag_id
                  AND t.project_id = app.current_project_id()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM asset_tags t
                WHERE t.id = asset_tag_links.tag_id
                  AND t.project_id = app.current_project_id()
            )
        )
        """
    )
    for table in _AVAILABILITY_TABLES:
        _replace_workspace_only_policy(table)

    op.execute("ALTER TABLE exports DROP CONSTRAINT IF EXISTS fk_exports_episode")
    op.execute(
        "ALTER TABLE shot_human_locks DROP CONSTRAINT IF EXISTS fk_shot_human_locks_shot"
    )
    # The 2-argument recovery overload was a retired surface, not a schema
    # requirement of any earlier revision; downgrade deliberately does not
    # resurrect it.
