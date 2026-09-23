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

## 创作体验改进：目标数据演进

**状态：迁移设计约束，待实现/待验收。** 本节不改变前文当前 Alembic head，也不预设
迁移编号、宣称新增列已存在或授权升级运行实例。实施范围见
[开发合同](ARCHITECTURE_MAPPING.md#creation-improvement-contract) 的 D1/D2/D5 与 AC-03/08/15/16。

### 连接与绑定身份

现有 `provider_connections` 按 workspace/provider/profile 的唯一约束不能承载同空间
两个兼容端点。目标是以连接 ID 为稳定身份，并保持不可变 connection/credential revision。
实施不止删除唯一约束，还必须逐项更新：

| 数据链 | 必须保持的约束 |
|---|---|
| Connection → revisions | 多条同协议连接独立保存/轮换/禁用；修订属于准确连接与空间；名称不是执行身份 |
| Model binding → contract | 绑定精确连接、远端 ID、模式与合同版本；同名模型不能按字符串合并 |
| Workspace default / project / Shot override | 使用既有 profile/绑定链和同一 resolver；读模型可说明继承；不能维护两份互相矛盾的默认 |
| Capability / quality evidence | 保留验证的 connection/credential revision、模型、模式及范围；旧成功/失败不覆盖新修订投影 |
| Frozen plan / NodeRun / ProviderOperation | 保存已解析身份；已受理历史任务不因默认选择、目录更新、Key 轮换而换到别的连接 |
| Cache / query / RLS | 缓存键与查询包含空间和连接身份；当前授权校验不能被缓存命中跳过；后台恢复仍用窄所有权查询 |

数据库可静态表达的 FK/唯一/CHECK 在数据库保证；跨 JSON 冻结结构的约束由版本化校验与
集成测试保证，不假设字符串相同即属于同一来源。部署级 alias 需要显式来源/可见性；
不是随便挑一条空间连接。详细规则由 MODEL_PROVIDER 的 MP-01/03/09 唯一维护。

迁移前构造含两个空间、旧 profile/绑定、历史证据、排队/已完成/未知提交任务的 fixture。
可以唯一映射的现有关系保持原 ID 与身份；无法唯一映射的**新执行选择**标明需重选，
不能猜测或丢弃。已有冻结历史仍可回读，恢复沿用其原始身份；所需凭证/合同确实不可用
时明确阻塞，不覆盖为最新值。不得批量重新认证、轮换 Key 或产生 Provider 调用。

### 编译快照与合同版本

沿用已有计划/NodeRun 的冻结输入和 ProviderOperation 审计结构，补齐 schema version、
模型/合同/compiler/prompt 策略版本、输入版本、最终语义请求、转换报告、引用 hash/顺序
及已接受近似。具体列或 JSON 扩展在实现迁移中确定，不新建与生产事实竞争的任务表。
完整冻结范围见 MP-07；公共投影与发送私有数据分离，凭证仍只存引用和既有加密版本。

只读预览可持久化有过期/清理策略的非秘密快照或返回可核验的计划；受理时必须把可重放的
精确语义内容绑定到原 NodeRun。不能只存一个 hash，却在 Worker 用新合同重新编译。
同命令幂等重放与用户明确再次生成使用不同身份；唯一约束范围不能把所有相同 prompt
永久合并。请求授权、提交标记、远端 ID 与恢复证据继续附着在原执行链。

旧 snapshot 按其 schema version 解释，保留原 payload/hash，不在迁移中“升级”改写。
变更运行所需的解析器时提供受限兼容读取和失败用例；无法忠实解释则阻止新发送，并给出
人工处置方式。已知远端任务优先对账/恢复，不能因新版解析器不认识旧格式而重新 create。

### 调度、预演与剪辑状态

RT 调度扩展可在既有 NodeRun/ProviderOperation/Outbox 归属中添加必要的到期时间、
claim/租约等字段及索引。持久恢复必须有有界分页、原子领取、过期竞争与权限测试；
不能通过增加平行任务表绕过现有状态机，不能在 Runtime 另建预算/批次真相。

动态分镜是 Shot/Artifact 与已保存创意数据的播放投影；播放位置、展开状态、缩放等
属于 UI 状态，不增加 Animatic 生产实体或伪造 Final Film。编辑仍由 EditSession
拥有 timeline 草稿及版本，预览不修改生产事实，导出绑定已保存版本。审片采用既有
annotation/decision 与精确 Artifact；不把旧片时间码或审批复制给新候选。

若为 UI-10 新增片段配音 gain，默认值必须保留旧时间线的实际响度；范围和单位由同一
timeline schema 校验，预览/导出消费同一值。不得复用背景音乐音量字段改变其旧语义。

### 迁移验收与交接

- 新增前向迁移，保持单一 Alembic head；不改已发布迁移、不清表后再证明成功。
- 检查唯一约束、索引、FK、CHECK、RLS 与实际查询计划；验证两空间、同名模型、Key
  轮换、禁用、跨空间猜 ID、旧 snapshot、并发领取、幂等冲突与进程丢失恢复。
- 迁移前后断言历史 ID/行、密文、凭证修订、ProviderOperation、Artifact 血缘、Formal
  指针与未知提交证据完整；测试输出不打印密钥/密文或私有创作载荷。
- 候选 PostgreSQL 中执行 upgrade/head/check 及迁移/RLS 集成门；数据库回退/应用回退
  的兼容窗口与恢复办法写在该实施变更中，不假设 destructive downgrade 安全。
- 部署前单独核实目标实例、备份和授权；文档开发与隔离 fixture 测试不授权生产迁移。
