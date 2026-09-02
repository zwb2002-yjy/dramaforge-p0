"""Hard-remove retired Creation, controlled Director, and identity tables.

The Owner explicitly withdrew historical compatibility and rollback.  This
revision therefore deletes the retired schema instead of adding aliases or
shadow tables.  Canonical Script/Scene/Shot, AssetVersionReference, Workbench,
ProviderOperation, Review, and EditSession tables remain intact.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260902_0051"
down_revision: str | None = "20260901_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_provider_operation_rls() -> None:
    """Remove the historical AgentRun branch before its column is dropped."""

    op.execute("DROP POLICY IF EXISTS provider_operations_project_scope ON provider_operations")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.project_id_for_provider_operation(p_id uuid)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT nr.project_id
          FROM provider_operations po
          JOIN node_runs nr ON nr.id = po.node_run_id
          WHERE po.id = p_id
        $$
        """
    )
    op.execute(
        """
        CREATE POLICY provider_operations_project_scope ON provider_operations
        FOR ALL
        USING (
          node_run_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM node_runs nr
            WHERE nr.id = provider_operations.node_run_id
              AND nr.project_id = app.current_project_id()
          )
        )
        WITH CHECK (
          node_run_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM node_runs nr
            WHERE nr.id = provider_operations.node_run_id
              AND nr.project_id = app.current_project_id()
          )
        )
        """
    )


def _drop_retired_tables(tables: Sequence[str]) -> None:
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def upgrade() -> None:
    # ProviderOperation is now NodeRun-owned only. Replace the RLS function and
    # policy first because the old definitions mention agent_runs.agent_run_id.
    _replace_provider_operation_rls()
    op.execute("DROP INDEX IF EXISTS uq_provider_operations_agent_attempt")
    op.execute(
        "ALTER TABLE provider_operations DROP COLUMN IF EXISTS agent_run_id CASCADE"
    )

    # NodeRun no longer carries controlled Director budget/batch lineage.
    op.execute("DROP INDEX IF EXISTS ix_node_runs_budget_reservation_id")
    op.execute("DROP INDEX IF EXISTS ix_node_runs_production_batch_id")
    op.execute(
        "ALTER TABLE node_runs DROP COLUMN IF EXISTS budget_reservation_id CASCADE"
    )
    op.execute(
        "ALTER TABLE node_runs DROP COLUMN IF EXISTS production_batch_id CASCADE"
    )

    # Drop controlled Director fact tables in dependency-safe reverse order.
    _drop_retired_tables(
        (
            "budget_reservations",
            "production_batch_shots",
            "production_batches",
            "director_issues",
            "workflow_step_runs",
            "impact_reports",
            "approval_records",
            "change_proposals",
            "budget_authorizations",
            "creative_artifact_versions",
            "director_workflow_runs",
        )
    )

    # Creation plans and their AgentRun/materialization support are retired;
    # Story will introduce a proposal contract separately after this cleanup.
    op.execute(
        "ALTER TABLE director_proposals DROP COLUMN IF EXISTS agent_run_id"
    )
    _drop_retired_tables(
        (
            "materialization_operations",
            "creation_plans",
            "creative_brief_revisions",
            "creative_briefs",
            "planning_authorizations",
            "agent_runs",
        )
    )

    # Identity is represented only by Asset → AssetVersion →
    # AssetVersionReference → ShotReferenceBinding.
    _drop_retired_tables(("character_references", "characters"))

    # Preferences keep the neutral workspace_state JSON only; mode/guide state
    # was the last persisted Quick/Workbench split.
    op.execute(
        "ALTER TABLE user_project_preferences DROP COLUMN IF EXISTS last_guided_step"
    )
    op.execute(
        "ALTER TABLE user_project_preferences DROP COLUMN IF EXISTS experience_mode"
    )

    for enum_name in (
        "materialization_operation_status",
        "agent_run_status",
        "creative_revision_source",
        "creation_plan_status",
        "agent_operation",
        "experience_mode",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")


def downgrade() -> None:
    raise RuntimeError(
        "20260902_0051 is an intentional irreversible hard removal; restore from a database backup"
    )
