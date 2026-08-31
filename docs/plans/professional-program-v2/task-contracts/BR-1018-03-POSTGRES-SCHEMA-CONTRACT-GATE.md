# Task: BR-1018-03 — PostgreSQL Schema Contract Gate

## Status

- **State:** BLOCKED — schema authority follow-up required
- **Program order:** Phase 4 Merge Gate CI contract evidence; no Phase 6+ work
- **Scope:** Add a strict `alembic check` gate after `alembic upgrade head` in the
  existing PostgreSQL 15 integration job and record the first real drift result.

## Current implementation evidence

- `.github/workflows/ci.yml` now runs, in this exact order, `uv run alembic
  upgrade head`, `uv run alembic check`, and `uv run pytest tests/integration -q
  -rs --fail-on-skip`. The job has no conditional or error-tolerant gate.
- `backend/tests/unit/test_ci_workflow_contract.py` statically verifies the
  PostgreSQL 15 service, all three commands, their order, and the absence of
  skip/advisory semantics.
- Local `dramaforge-ci-pg` is PostgreSQL 15, reachable on `127.0.0.1:5432`,
  database `dramaforge`. Before the check, `alembic current` reported
  `20260827_0049 (head)` and the database contained 71 public tables.
- `python -m alembic upgrade head` exited 0. The database was already at head;
  no migration was applied by this idempotent run.
- `python -m alembic check` exited 1. It reported 109 schema differences and
  one non-drift SERIAL-owned-sequence informational message. No generated or
  automatic migration was created or applied.

## Exact drift reported by `alembic check`

The following is the complete categorized diff from the run above. Names and
column mappings are copied from Alembic's `Detected ...` lines.

### Table

- Removed table: `materialization_operations`.

This is an ORM comparison result only. The table remains materialized and must
not be deleted in this follow-up.

### Removed indexes (35)

```text
idx_materialization_operations_project_plan
idx_agent_runs_claim
idx_artifacts_project_state
ix_asset_version_references_version
idx_asset_versions_project_asset
ix_assets_current_version_id
idx_canvas_revisions_project_shot
idx_creation_plans_project_status
idx_brief_revisions_project_status
idx_creative_briefs_project
ix_director_messages_thread
ix_director_proposal_items_proposal
ix_director_proposals_scope
ix_encrypted_provider_credential_supersedes_id
idx_event_log_project_occurred
idx_experiment_branches_project
idx_graph_edges_downstream
idx_node_runs_cache_lookup
idx_node_runs_reused_from
idx_planning_authorizations_project_expiry
uq_model_profile_workspace_default
idx_projects_workspace_stage
ix_provider_connection_revisions_connection_id
ix_provider_operations_connection_revision_id
uq_provider_operations_agent_attempt
uq_provider_operations_node_run
uq_provider_operations_remote
idx_review_annotations_project_shot
idx_shot_change_proposals_project_shot
ix_shot_experiments_shot
ix_shot_reference_bindings_shot
idx_shots_project_scene
ix_shots_formal_composite_artifact_id
ix_shots_formal_keyframe_artifact_id
ix_shots_formal_video_artifact_id
```

### Removed foreign keys (14)

```text
agent_runs.result_brief_revision_id
agent_runs.target_brief_revision_id
agent_runs.target_plan_id
agent_runs.result_plan_id
approval_records.invalidated_by_proposal_id
artifacts.produced_by_run_id
creation_plans.source_agent_run_id
creative_brief_revisions.supersedes_revision_id
creative_brief_revisions.source_agent_run_id
creative_briefs.current_revision_id
graph_nodes.latest_successful_run_id
node_runs.parent_run_id
node_runs.reused_from_run_id
node_runs.result_artifact_id
```

### Unique constraints

Removed (5):

```text
creative_brief_revisions_creative_brief_id_revision_no_key
creative_brief_revisions_id_project_id_key
graph_edges_graph_version_id_downstream_node_id_input_port__key
graph_edges_graph_version_id_upstream_node_id_output_port_d_key
node_runs_graph_node_id_attempt_no_key
```

Added (4):

```text
uq_brief_rev_id_project (creative_brief_revisions.id, project_id)
uq_brief_rev_no (creative_brief_revisions.creative_brief_id, revision_no)
uq_graph_edges_identity (graph_edges.graph_version_id, upstream_node_id,
  output_port, downstream_node_id, input_port, position)
uq_graph_edges_input_position (graph_edges.graph_version_id,
  downstream_node_id, input_port, position)
```

### Added indexes (1)

```text
ix_provider_operations_provider_connection_revision_id
  (provider_operations.provider_connection_revision_id)
```

### Type changes (49)

`CHAR(64) → String(64)`:

```text
artifacts.content_hash
graph_versions.definition_hash
node_runs.input_hash
provider_operations.request_fingerprint
```

`CHAR(3) → String(3)`:

```text
planning_authorizations.currency
projects.budget_currency
provider_operations.currency
```

`JSONB → JSON`:

```text
asset_version_references.metadata
asset_versions.metadata
assets.metadata
creation_plans.plan
creative_brief_revisions.brief
director_board_states.camera
director_board_states.characters
director_board_states.scene
director_messages.metadata
director_proposal_items.payload
edit_sessions.timeline
edit_sessions.production_lineage
event_log.payload
experiment_branches.source_artifact_ids
experiment_branches.candidate_artifact_ids
experiment_branches.comparison
experiment_branches.adopted_shot_ids
experiment_branches.parameters
export_items.metadata
exports.manifest
graph_nodes.input_schema
graph_nodes.output_schema
graph_nodes.config
graph_versions.definition
node_runs.input_snapshot
node_runs.output_summary
outbox_dead_letters.payload
outbox_events.payload
projects.style_bible
provider_operations.request_summary
provider_operations.response_summary
provider_operations.token_usage
shot_change_proposals.replacement_payload
shot_change_proposals.affected_node_keys
shot_change_proposals.reusable_artifact_ids
shot_experiments.director_state
shot_experiments.prompts
shot_experiments.references
shot_experiments.model_overrides
shot_experiments.common_controls
shot_experiments.comparison
shot_reference_bindings.metadata
```

## Blocker and next bounded task

The new strict CI gate correctly blocks on pre-existing ORM/schema authority
drift. The next task must handle **schema authority only**: reconcile the
canonical ORM metadata with the migration-defined PostgreSQL schema (or record
intentional exclusions in the comparison contract), while preserving
`materialization_operations`, existing migrations, execution-identity fixes,
and all other runtime/product boundaries. It must not guess a destructive
normalization migration, run `create_all`, use SQLite, globally ignore drift,
or expand Provider/runtime/UI scope.
