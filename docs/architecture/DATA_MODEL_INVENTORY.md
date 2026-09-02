# DATA_MODEL_INVENTORY

Status: current candidate
Date: 2026-09-03
Alembic head: 20260903_0052

## Canonical relational graph

users → workspaces → projects
projects → script_documents → episodes → scenes → shots
projects → project_creative_profiles
projects → assets → asset_versions → asset_version_references
shots → shot_reference_bindings
shots → production_graphs → graph_versions → graph_nodes/graph_edges
graph_nodes → node_runs → provider_operations → artifacts
shots → review_annotations / shot_change_proposals
projects → director_threads → director_messages
director_threads → director_proposals → director_proposal_items
projects → edit_sessions → exports

## Model ownership

| Domain | Canonical tables | ORM location |
|---|---|---|
| Access | users, workspaces, projects, user_project_preferences.workspace_state | app/access/models.py |
| V1 creative profile | project_creative_profiles | app/access/models.py |
| Story | script_documents, episodes, scenes, shots, canvas_revisions, shot_change_proposals | app/assets/models.py |
| Identity assets | assets, asset_versions, asset_version_references, asset_tags | app/assets/models.py |
| Shot references | shot_reference_bindings, shot_experiments | app/production/models.py |
| Execution | production_graphs, graph_versions, graph_nodes, graph_edges, node_runs, artifacts, provider_operations | app/production/models.py and app/execution/models.py |
| Assistant | director_threads, director_messages, director_proposals, director_proposal_items | app/director/assistant_models.py and proposal_models.py |
| Review/Delivery | review_annotations, exports, export_items | app/delivery/models.py |
| Editing | edit_sessions | app/editing/models.py |
| Provider identity | connections, connection revisions, model bindings, catalog/evidence | app/providers/models.py and provider model profile modules |

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

Migration 20260903_0052 adds `project_creative_profiles`
(start_type / template identity / director_autonomy / selected creative
defaults / asset slot requirements / frozen strategy snapshot / optimistic
version).  It only initializes project facts and never owns Runtime.

No canonical Project, Shot, Artifact, ProviderOperation, or EditSession is
deleted by this migration. Historical data migration and rollback are not
required by the Owner revision.

## Schema invariants

- Alembic has one head: 20260903_0052.
- Metadata registration is centralized in app/shared/model_registry.py.
- ProviderOperation is NodeRun-owned only.
- identity reference resolution is explicit and version-pinned.
- migration 0051 is the only owner of the hard-removal operation.
