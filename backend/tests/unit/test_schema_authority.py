"""Regression checks for migration-owned SQLAlchemy schema authority."""

from __future__ import annotations

from app.shared.base import Base
from app.shared.model_registry import load_all_models
from sqlalchemy import CHAR
from sqlalchemy.dialects.postgresql import JSONB, dialect


def _metadata() -> None:
    load_all_models()


def test_materialization_operations_is_registered_without_a_crud_model() -> None:
    _metadata()
    table = Base.metadata.tables["materialization_operations"]

    assert [column.name for column in table.columns] == [
        "id",
        "project_id",
        "creation_plan_id",
        "operation_key",
        "operation_kind",
        "payload_hash",
        "status",
        "result_entity_type",
        "result_entity_id",
        "error_code",
        "created_at",
        "completed_at",
    ]
    assert [column.name for column in table.primary_key.columns] == ["id"]
    assert {
        (foreign_key.name, tuple(foreign_key.column_keys), foreign_key.ondelete)
        for foreign_key in table.foreign_key_constraints
    } == {
        (None, ("project_id",), "CASCADE"),
        (None, ("creation_plan_id",), "CASCADE"),
    }
    assert table.indexes and {
        index.name for index in table.indexes
    } == {"idx_materialization_operations_project_plan"}


def test_postgresql_document_and_fixed_width_types_match_migrations() -> None:
    _metadata()
    pg = dialect()

    jsonb_columns = {
        ("asset_version_references", "metadata"),
        ("asset_versions", "metadata"),
        ("assets", "metadata"),
        ("creation_plans", "plan"),
        ("creative_brief_revisions", "brief"),
        ("director_board_states", "camera"),
        ("director_board_states", "characters"),
        ("director_board_states", "scene"),
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
        ("shot_experiments", "common_controls"),
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
        ("planning_authorizations", "currency"),
        ("projects", "budget_currency"),
        ("provider_operations", "currency"),
    ):
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type, CHAR)
        assert column.type.length == 3


def test_named_foreign_keys_unique_constraints_and_indexes_follow_history() -> None:
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
            "creative_briefs",
            "current_revision_id",
            "fk_creative_briefs_current_revision",
            "creative_brief_revisions.id",
            "RESTRICT",
            True,
        ),
        (
            "creative_brief_revisions",
            "source_agent_run_id",
            "fk_brief_revision_source_agent_run",
            "agent_runs.id",
            "RESTRICT",
            True,
        ),
        (
            "creation_plans",
            "source_agent_run_id",
            "fk_creation_plan_source_agent_run",
            "agent_runs.id",
            "RESTRICT",
            True,
        ),
        (
            "approval_records",
            "invalidated_by_proposal_id",
            "fk_approval_invalidating_proposal",
            "change_proposals.id",
            "SET NULL",
            None,
        ),
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

    for table_name, names in {
        "creative_brief_revisions": {
            "creative_brief_revisions_creative_brief_id_revision_no_key",
            "creative_brief_revisions_id_project_id_key",
        },
        "graph_edges": {
            "graph_edges_graph_version_id_downstream_node_id_input_port__key",
            "graph_edges_graph_version_id_upstream_node_id_output_port_d_key",
        },
        "node_runs": {"node_runs_graph_node_id_attempt_no_key"},
    }.items():
        actual = {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert names <= actual

    expected_indexes = {
        "idx_materialization_operations_project_plan",
        "idx_artifacts_project_state",
        "idx_agent_runs_claim",
        "idx_graph_edges_downstream",
        "idx_node_runs_cache_lookup",
        "idx_node_runs_reused_from",
        "ix_provider_operations_connection_revision_id",
        "uq_provider_operations_node_run",
        "uq_provider_operations_agent_attempt",
        "uq_provider_operations_remote",
    }
    actual_indexes = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    assert expected_indexes <= actual_indexes
