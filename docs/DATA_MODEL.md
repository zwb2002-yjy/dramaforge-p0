# DATA_MODEL — 数据模型权威

Status: current
Date: 2026-09-16
Base: dev 6555395
Alembic head: 20260916_0070
Revisions: 70
（入口见 [CURRENT.md](CURRENT.md)）

## Canonical relational graph

users → workspaces → projects
projects → script_documents → episodes → scenes → shots
projects → project_creative_profiles
projects → assets → asset_versions → asset_version_references
assets → asset_tags → asset_tag_links
shots → shot_reference_bindings
shots → production_graphs → graph_versions → graph_nodes/graph_edges
graph_nodes → node_runs → provider_operations → artifacts
shots → shot_human_locks
shots → review_annotations / shot_change_proposals
projects → director_threads → director_messages
projects → director_turns → director_invocations
director_threads → director_proposals → director_proposal_items
projects → director_inbox / director_wakeups
director_turns → director_runtime_controls → director_runtime_wakeups / director_runtime_signal_claims
shots → production_experiments / shot_experiments / experiment_branches
projects → production_command_authorizations
projects → edit_sessions → exports → export_items
projects → event_log / outbox_events / outbox_dead_letters

## Model ownership

| Domain | Canonical tables | ORM location |
|---|---|---|
| Access | users, workspaces, projects, user_project_preferences, instance_bootstrap_state | app/access/models.py |
| V1 creative profile | project_creative_profiles | app/access/models.py |
| Story | script_documents, episodes, scenes, shots, canvas_revisions, shot_change_proposals | app/assets/models.py |
| Identity assets | assets, asset_versions, asset_version_references, asset_tags, asset_tag_links | app/assets/models.py |
| Shot references | shot_reference_bindings, shot_experiments | app/production/models.py |
| Production graph | production_graphs, graph_versions, experiment_branches, director_board_states, production_experiments | app/production/models.py |
| Approved commands | production_command_authorizations | app/production/command_models.py |
| Execution | graph_nodes, graph_edges, node_runs, artifacts, provider_operations, shot_human_locks | app/execution/models.py |
| Assistant | director_threads, director_messages, director_proposals, director_proposal_items | app/director/assistant_models.py and proposal_models.py |
| Director turns | director_turns, director_invocations, director_inbox, director_wakeups | app/director/turn_models.py, invocation_models.py, inbox_models.py |
| Director engine control | director_runtime_controls, director_runtime_wakeups, director_runtime_signal_claims | app/director/runtime/models.py |
| Review/Delivery | review_annotations, exports, export_items | app/delivery/models.py |
| Editing | edit_sessions | app/editing/models.py |
| Events | event_log, outbox_events, outbox_dead_letters | app/events/models.py |
| Security | encrypted_provider_credentials, key_rotation_audits | app/security/models.py |
| Provider identity | provider_connections, provider_connection_revisions, provider_capability_evidence, provider_model_bindings, project_provider_bindings, provider_quality_evidence, artifact_reference_tokens | app/providers/models.py |
| Provider catalog/profile | provider_model_catalog_entries, production_model_profiles | app/providers/catalog_models.py, app/providers/model_profiles/orm.py |

A second, private schema `director_runtime_checkpoints` (LangGraph checkpoint
tables `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
`checkpoint_migrations`) is owned by the dedicated
`dramaforge_director_checkpoint` role. It is revoked from `PUBLIC` and
`dramaforge_app` and is never part of the application model registry.

## Removed tables and columns

Migration 20260902_0051 removes:

- Creation tables: creative_briefs, creative_brief_revisions, creation_plans,
  planning_authorizations, agent_runs, materialization_operations;
- controlled Director tables: director_workflow_runs,
  creative_artifact_versions, budget_authorizations, approval_records,
  change_proposals, impact_reports, workflow_step_runs, director_issues,
  production_batches, production_batch_shots, budget_reservations;
- identity tables: characters and character_references;
- NodeRun production_batch_id and budget_reservation_id;
- ProviderOperation agent_run_id;
- user_project_preferences experience_mode and last_guided_step;
- their retired PostgreSQL enum types and constraints.

## Additions after the hard removal

| Revision | Addition |
|---|---|
| 20260903_0052 | `project_creative_profiles` (start_type / template identity / director_autonomy / creative defaults / asset slot requirements / frozen strategy snapshot / optimistic version) — project facts only, never Runtime. |
| 20260903_0053 | Project-scoped Final Film assembly graph scope. |
| 20260903_0054 | Explicit idempotency key on exports. |
| 20260903_0055 | Persisted credential revision identity on ProviderOperation. |
| 20260907_0056 | Bounded Director turns and text invocation evidence. |
| 20260908_0057–0060 | Recovery functions/grants for recoverable Director turns, fact reconciliation, Formal checkpoints and cancellation-requested Provider work. |
| 20260909_0061 | `production_command_authorizations`: exact user-approved commands persisted before Director submission. |
| 20260909_0062 | `director_inbox`, `director_wakeups`: atomic receipt/wakeup retention across process loss. |
| 20260910_0063 | `app.emit_workbench_terminal_notice()` trigger on every `node_runs.status` write. |
| 20260910_0064 | `director_invocations`: individual Director text invocation identity and validated output. |
| 20260910_0065 | Director turn engine binding (`engine_version`, `state_schema_version`, `runtime_execution_id`, `runtime_revision`) and `director_runtime_controls`, `director_runtime_wakeups`, `director_runtime_signal_claims`. |
| 20260910_0066 | Private `director_runtime_checkpoints` schema and its role. |
| 20260916_0070 | Canonical Asset/AssetVersion lifecycle constraints, current Formal pointers, and one-time migration of legacy `metadata.tags` into `asset_tags` / `asset_tag_links`. |

No canonical Project, Shot, Artifact, ProviderOperation, or EditSession is
deleted by these revisions. Revision 0070 backfills legacy Asset lifecycle and
tag data before enforcing the canonical constraints.

## Schema invariants

- Alembic has one head: 20260916_0070.
- Metadata registration is centralized in app/shared/model_registry.py.
- ProviderOperation is NodeRun-owned only.
- Identity reference resolution is explicit and version-pinned.
- Asset status is limited to `draft | active | recycled`; AssetVersion status
  is limited to `candidate | formal | historical | rejected`, and each current
  Formal version is addressed by `assets.current_version_id`.
- Asset tags are sourced only from `asset_tags` / `asset_tag_links`.
- Migration 0051 is the only owner of the hard-removal operation.
- Director engine identity is all-or-nothing per turn
  (`ck_director_turn_engine_binding`) and `runtime_execution_id` is unique.
