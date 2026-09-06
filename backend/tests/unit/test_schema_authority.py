"""Regression checks for the canonical migration-owned SQLAlchemy schema."""

from __future__ import annotations

from app.shared.base import Base
from app.shared.model_registry import load_all_models
from sqlalchemy import CHAR
from sqlalchemy.dialects.postgresql import JSONB, dialect


def _metadata() -> None:
    load_all_models()


def test_retired_models_are_not_registered() -> None:
    _metadata()
    tables = set(Base.metadata.tables)
    assert not {
        "creative_briefs",
        "creative_brief_revisions",
        "creation_plans",
        "planning_authorizations",
        "agent_runs",
        "materialization_operations",
        "director_workflow_runs",
        "creative_artifact_versions",
        "budget_authorizations",
        "approval_records",
        "change_proposals",
        "impact_reports",
        "workflow_step_runs",
        "director_issues",
        "production_batches",
        "production_batch_shots",
        "budget_reservations",
        "characters",
        "character_references",
    } & tables


def test_canonical_schema_registers_required_tables() -> None:
    _metadata()
    assert {
        "projects",
        "script_documents",
        "episodes",
        "scenes",
        "shots",
        "assets",
        "asset_versions",
        "asset_version_references",
        "shot_reference_bindings",
        "node_runs",
        "provider_operations",
        "director_threads",
        "director_messages",
        "director_proposals",
        "director_proposal_items",
        "edit_sessions",
    } <= set(Base.metadata.tables)


def test_postgresql_document_and_fixed_width_types_match_migrations() -> None:
    _metadata()
    pg = dialect()
    jsonb_columns = {
        ("asset_version_references", "metadata"),
        ("asset_versions", "metadata"),
        ("assets", "metadata"),
        ("director_messages", "metadata"),
        ("director_proposal_items", "payload"),
        ("edit_sessions", "timeline"),
        ("edit_sessions", "production_lineage"),
        ("event_log", "payload"),
        ("experiment_branches", "source_artifact_ids"),
        ("experiment_branches", "candidate_artifact_ids"),
        ("experiment_branches", "comparison"),
        ("experiment_branches", "adopted_shot_ids"),
        ("experiment_branches", "parameters"),
        ("export_items", "metadata"),
        ("exports", "manifest"),
        ("graph_nodes", "input_schema"),
        ("graph_nodes", "output_schema"),
        ("graph_nodes", "config"),
        ("graph_versions", "definition"),
        ("node_runs", "input_snapshot"),
        ("node_runs", "output_summary"),
        ("outbox_dead_letters", "payload"),
        ("outbox_events", "payload"),
        ("projects", "style_bible"),
        ("provider_operations", "request_summary"),
        ("provider_operations", "response_summary"),
        ("provider_operations", "token_usage"),
        ("shot_change_proposals", "replacement_payload"),
        ("shot_change_proposals", "affected_node_keys"),
        ("shot_change_proposals", "reusable_artifact_ids"),
        ("shot_experiments", "director_state"),
        ("shot_experiments", "prompts"),
        ("shot_experiments", "references"),
        ("shot_experiments", "model_overrides"),
        ("shot_experiments", "comparison"),
        ("shot_reference_bindings", "metadata"),
    }
    for table_name, column_name in jsonb_columns:
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type.dialect_impl(pg), JSONB), (table_name, column_name)

    for table_name, column_name in (
        ("artifacts", "content_hash"),
        ("graph_versions", "definition_hash"),
        ("node_runs", "input_hash"),
        ("provider_operations", "request_fingerprint"),
    ):
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type, CHAR)
        assert column.type.length == 64

    for table_name, column_name in (
        ("projects", "budget_currency"),
        ("provider_operations", "currency"),
    ):
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type, CHAR)
        assert column.type.length == 3


def test_canonical_foreign_keys_and_indexes_remain_named() -> None:
    _metadata()

    def foreign_key(table_name: str, column_name: str):
        table = Base.metadata.tables[table_name]
        return next(
            constraint
            for constraint in table.foreign_key_constraints
            if column_name in constraint.column_keys
        )

    for table_name, column_name, name, target, ondelete, deferrable in (
        (
            "artifacts",
            "produced_by_run_id",
            "fk_artifacts_produced_by_run",
            "node_runs.id",
            "RESTRICT",
            True,
        ),
        (
            "graph_nodes",
            "latest_successful_run_id",
            "fk_graph_nodes_latest_successful_run",
            "node_runs.id",
            "SET NULL",
            True,
        ),
        (
            "node_runs",
            "result_artifact_id",
            "fk_node_runs_result_artifact",
            "artifacts.id",
            "RESTRICT",
            True,
        ),
    ):
        constraint = foreign_key(table_name, column_name)
        element = next(item for item in constraint.elements if item.parent.name == column_name)
        assert constraint.name == name
        assert element.target_fullname == target
        assert constraint.ondelete == ondelete
        assert constraint.deferrable is deferrable
        assert constraint.initially == ("DEFERRED" if deferrable else None)

    assert "production_batch_id" not in Base.metadata.tables["node_runs"].c
    assert "budget_reservation_id" not in Base.metadata.tables["node_runs"].c
    assert "agent_run_id" not in Base.metadata.tables["provider_operations"].c
    expected_indexes = {
        "idx_artifacts_project_state",
        "idx_graph_edges_downstream",
        "idx_node_runs_cache_lookup",
        "idx_node_runs_reused_from",
        "ix_provider_operations_connection_revision_id",
        "uq_provider_operations_node_run",
        "uq_provider_operations_remote",
    }
    actual_indexes = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    assert expected_indexes <= actual_indexes
