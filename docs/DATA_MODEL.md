# DATA_MODEL — 数据模型权威

Status: current
Date: 2026-09-22
Alembic head: 20260922_0077
Revisions: 77
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
shots → experiment_branches
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
| Shot references | shot_reference_bindings | app/production/models.py |
| Production graph | production_graphs, graph_versions, experiment_branches, director_board_states | app/production/models.py |
| Archived experiment storage (not product authority) | production_experiments, shot_experiments | app/production/archive_models.py |
| Approved commands | production_command_authorizations | app/production/command_models.py |
| Execution | graph_nodes, graph_edges, node_runs, artifacts, provider_operations, shot_human_locks | app/execution/models.py |
| Assistant | director_threads, director_messages, director_proposals, director_proposal_items | app/director/assistant_models.py and proposal_models.py |
| Director turns | director_turns, director_invocations, director_inbox, director_wakeups | app/director/turn_models.py, invocation_models.py, inbox_models.py |
| Director engine control | director_runtime_controls, director_runtime_wakeups, director_runtime_signal_claims | app/director/runtime/models.py |
| Review/Delivery | review_annotations, human_review_decisions, exports, export_items | app/delivery/models.py |
| Staged repair | repair_requests, repair_steps | app/production/models.py |
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

## RLS scope discovery and transaction context

`app/shared/rls_scopes.py` discovers persisted ownership for NodeRun, Artifact,
Outbox and Director recovery. PostgreSQL paths call only the existing narrow
SECURITY DEFINER functions; resolver failures never fall back to unrestricted ORM
reads. Non-PostgreSQL queries exist for local/test execution, retain source-commit
filters and skip orphaned ownership chains.

`app/shared/db.py` owns engines, sessions and transaction-local RLS application.
It explicitly re-exports the scope types and discovery entrypoints for existing
callers. Missing ownership or an Artifact workspace mismatch never applies a new
owner scope. Commit/recovery callers still reapply context for each transaction;
this module split changes no table, policy, resolver function or migration.

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
| 20260917_0071 | Remove the retired `face_review` node type and unused `export_format` / `export_status` PostgreSQL enum types; `project_stage` now reuses the shared ORM enum definition. |
| 20260917_0072 | Add a SECURITY DEFINER outbox metrics query for process-wide pending count and oldest pending age. |
| 20260919_0073 | Add bounded persisted Provider recovery discovery. |
| 20260921_0074 | Persist the model IDs returned by immutable account catalog probe evidence. |
| 20260921_0075 | Bind `provider_capability_evidence` to immutable `provider_connection_revisions` identity. |
| 20260921_0076 | Seed protocol-level OpenAI-compatible image/video capability contracts (contracts, not concrete supplier models). |
| 20260922_0077 | `human_review_decisions.decision` adds `demo_confirmed`; it records walkthrough confirmation but does not admit Formal media. |

No canonical Project, Shot, Artifact, ProviderOperation, or EditSession is
deleted by these revisions. Revision 0070 backfills legacy Asset lifecycle and
tag data before enforcing the canonical constraints.

## Schema invariants

- Alembic has one head: 20260922_0077 (verify with `alembic heads` on the candidate).
- Metadata registration is centralized in app/shared/model_registry.py.
- ProviderOperation is NodeRun-owned only.
- Identity reference resolution is explicit and version-pinned.
- Asset status is limited to `draft | active | recycled`; AssetVersion status
  is limited to `candidate | formal | historical | rejected`, and each current
  Formal version is addressed by `assets.current_version_id`.
- Asset tags are sourced only from `asset_tags` / `asset_tag_links`.
- Migration 0051 owns the retired Creation/controlled-Director/identity removals;
  migration history is not rewritten to make the current tree look smaller.
- Director engine identity is all-or-nothing per turn
  (`ck_director_turn_engine_binding`) and `runtime_execution_id` is unique.

## 历史实验记录

当前实验唯一事实是 ExperimentBranch，HTTP 与 Director 共享创建服务。
production_experiments / shot_experiments 的 ORM 已隔离到
app/production/archive_models.py；迁移与历史 RLS 测试保留，
以便既有持久数据仍可管理；没有当前运行时读取/写入或独立采用服务。
不以本次收口为由删除历史表或伪造迁移后的候选结果。Golden fixture 使用当前
ExperimentBranch，不再为旧轨制造新样本。

## 数据库清理准入

先判断前端/Worker/运维是否需要该能力，再判断当前表、字段或入口是否是它的唯一
实现。没有前端页面、表为空、类名含 legacy，都不构成删表依据。

- 当前实验能力由 ExperimentBranch 完整拥有；旧实验表不再回接前端。历史映射
  只由 model_registry 加载以保证 Alembic/ORM 一致性；运行时业务模块禁止导入。
- 保留旧表不等于允许旧轨复活。后续物理删除必须独立确认目标实例、备份/留存、
  旧版本退役与 FK/RLS/历史 JSON 引用处理，再新增前向迁移；不能直接改旧迁移。
- shot_reference_bindings.shot_experiment_id 等历史字段的去除，还需核对已冻结
  execution-plan JSON 与指纹兼容；不能用旧字段为前端发明新的实验分支功能。
- 私有 checkpoint schema、Outbox、死信、审计、凭证版本是基础设施事实，不能
  因无直接 UI 或当下无行就清空；凭证密文及私密载荷不进入清理报告。
- 运行实例和源码 revision 必须分别核对。临时发布实例或旧 revision 不是当前
  工作树的自动迁移目标；本轮不对持久实例执行升级、DROP、TRUNCATE 或 DELETE。
- schema 比对使用 PostgreSQL 对 CHECK 表达式的解析/反解与完整名称集比较，
  不过滤“多出来”的真实约束；历史数据保留测试也不算当前产品功能测试。
