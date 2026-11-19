# DATA_MODEL — 数据模型权威

Status: current
Date: 2026-11-18
Alembic head: 20261118_0119（0119给production_model_profiles新增media_config_version/image/video/voice三个binding与voice_options、项目行三binding组合FK与workspace-level空媒体CHECK，旧行回填version=1；0118给artifact_reference_tokens新增公共身份四列与三个组合FK并替换token解析函数；0117给asset_versions新增creation_request_key/hash与CHECK/部分唯一索引；0116新增adoption_request_key/hash/adopted_asset_revision与CHECK/部分唯一索引；0115给shot_reference_bindings新增public_asset_link_id/publication_item_id与单源CHECK、公共链接组合FK、resolution_mode新增public_link；0114新增公共资产三表、AssetVersion两个公共base列与组合FK、asset_versions/asset_version_references候选键；0113新增独立知识四表、knowledge_entry_guard指针守卫、research/knowledge的search_text投影列与pg_trgm GIN索引；0112只新增queued research-analysis Turn的窄作用域扫描函数`app.pending_research_analysis_turns`；0111新增研究分析清单/调用证据/结果链接三表与ProjectFileRevision.current_analysis_id；0110新增研究结果/不可变修订/引用三表与current指针守卫，并给director_invocations补(id,project_id)候选键；0109为解析受理冻结处理器profile并加事件schema2部分唯一表达式索引，无新表；0108只新增BusinessFlow Worker扫描函数`app.pending_business_flow_contexts`；0107新增BusinessFlow实例/步骤/尝试三表、Turn→Attempt链接与NodeRun/批准命令候选键；0106新增/替换导演Worker的窄作用域SECURITY DEFINER扫描；此前0100–0105为项目意图、解析快照、MasterRun、外发策略/目的地、来源用途与引用准入；隔离质量库已验证升级/约束与0109升降级，当前本地运行库仍为20261113_0099）

当前 Alembic 入口跨越 0084 前强制检查已存在的两张实验表和十张旧模型保障表，锁表后
非空即阻断升级；事务回滚保留原数据和迁移版本。空库初始化中历史迁移生成的静态目录副本
不等于运行前存在的业务证据。离线 SQL 无法进行该检查，跨 0084 时阻断输出。
也可在维护权限下运行 `scripts/audit_model_migration.py`：以 PostgreSQL READ ONLY
事务核对 0084 涉及的两张实验表和十张旧模型保障表，非空时退出码 1，要求先归档并核验
恢复。该命令不执行迁移、不删除数据、不把备份存在当作恢复通过；不改写已冻结的 0084。
Revisions: 123（Git HEAD基线含103项；工作区新增0100–0119，容器内alembic heads确认唯一源码头；隔离质量库已验证升降级边界与无模型漂移，本地实例未升级）
（入口见 [CURRENT.md](CURRENT.md)）

### 项目资料原件与提取

`project_files` 是项目私有资料关联，`content_version` 指向当前内容序号，`version`
用于并发更新/解除关联。`project_file_revisions` 保存不可变原件位置、hash、大小、文件名、
类型和上传幂等身份；提取状态及带位置的原文片段归属于确切修订，不是 AI 研究结论。
复合外键阻止修订串项目，两个表均强制项目 RLS。原件对象键按项目与内容 hash 分区，
相同字节可共享项目内对象，但关联、提取结果与授权不合并；不对外暴露跨项目去重结果。

更新追加修订并保留历史；解除关联只设置 detached_at，历史来源标记不可用，不能继续
作为当前有效依据。提取旧修订不修改当前版本。用户研究修正、研究历史及模型分析尚未
接入本表，不得用原文提取冒充分析。上传与提取请求 Outbox 同事务；重试身份保存在
对应修订的 extraction_requested 事件中，处理再次失败后的网络重发也不新增任务。
HTTP 上传与现有 dispatcher 中的资料处理循环已接入；界面和语义研究尚未接入。
0099 增加 attempt 与 pending 扫描索引，重试递增 attempt，迟到的成功/失败结果不能
覆盖新的重试。受限的 pending_project_file_contexts 只返回待处理修订及数据库确定的
归属；处理前重新鉴权。待处理状态在 PostgreSQL，进程重启后扫描恢复，Outbox 保持
事务性通知职责。单文件处理、失败回执与扫描分别有界；失败回执不可写时保持 pending。

0098 降级在存在资料关联时明确阻断，须先另行确定归档/恢复方案；空表可降级。回滚代码
不删除对象存储原件。事务回滚留下的内容寻址对象不得即时补偿删除，因为可能被其它
已提交关联引用；后续回收须核对引用与当前用途。

### 调度索引与历史保留

Outbox 未发布、Director 待唤醒、NodeRun 排队索引由迁移维护。
`test_scheduler_index_plans_pg.py` 在含 50,000 条已发布事件、20,000 条已完成
唤醒和 20,000 量级 NodeRun 历史的独立数据库中执行 `EXPLAIN (ANALYZE,
BUFFERS)`，并从数据库提取当前 `queued_node_run_contexts` 函数体核对真实调度
查询，而非只检查旧的 queued 条件。该规模通过不等于所有数据分布的延迟承诺。

历史命令、JSONB 授权账本的长期增长/锁等待仍属 P2 容量债，负责人为项目 Owner。
退出条件是在代表性项目与并发写入负载下记录实际查询计划、锁等待和 p95，再决定
索引或单独归档合同；当前未实施自动删除、TTL 或重新授权。容量优化不得清除
审计、未知提交或冻结身份，也不能把历史授权重新用于新 Create。

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
| Provider catalog/profile | provider_model_catalog_entries, production_model_profiles, provider_availability_evidence, provider_model_availability | app/providers/catalog_models.py, app/providers/model_profiles/orm.py, app/providers/availability_models.py |

当前仅保留文件目录/具体 Binding 与连接修订、逐模型可用性证据/投影。证据追加且不可改写。
同 provider/profile 连接可以并存；模型必须选择具体身份。历史两条父链在 0083 汇合，
当前 0084 进行单向清理：未接入的过渡表与旧实验表退役，引用字段统一为
`experiment_branch_id`。非空旧实验表阻止清理，必须单独归档，不自动转换成当前事实。

Asset tag 归一化由运行时 `str.strip().casefold()` 决定；0096 将 0070 历史 SQL `lower()`
键收敛到同一规则。同项目等价拼写优先保留已有 canonical ID，否则保留最早 ID；合并前
迁移全部资产关联，重复关联保留最早创建时间。不同项目不合并。正常运行不做标签 GC；
该数据迁移不反向重建旧的重复词汇 ID，降级后仍保留 canonical 键及全部关联。
显示名仍最多 80 字符；派生查找键使用 Text，容纳 casefold 的字符展开。存在超过 80 字符
的 canonical 键时拒绝缩回旧列宽，不截断数据。
终态通知触发器与 outbox 事实依赖写入事务先设置
project/user GUC；新增直接写 NodeRun 终态的代码必须沿用同一前提，否则通知事实不完整。
新增明确合同 revision，不改写旧 Manifest/hash；不提供回旧系统的 downgrade。
旧实例数据卷单独保管，当前开发环境使用新数据库并应用完整迁移链。

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
| 20260929_0074–0077 | Model-system branch: Global/Connection targets and availability; immutable product-policy, model-history, protocol and handler revisions. The unused parallel schema is removed by the current cleanup head. |
| 20260929_0078–20260930_0082 | Local-media branch: SGLang H3 contracts, MiniMax H3 v2 text/video contract, and separate bindings per contract revision. |
| 20261007_0084 | One-way cleanup of unused cutover/experiment storage and obsolete fields; one model authority, multiple independent connections, explicit new contract revisions. |
| 20261007_0085 | `projects.deleted_at` and uniqueness of names among active projects. Deleted projects leave the workbench; production/provider evidence and media remain under their original IDs. |
| 20261008_0086 | Remove the retired `audio.tts` key from `production_model_profiles.bindings`; voice execution remains owned by frozen `voice_execution` facts. |
| 20261008_0087 | Remove workspace-entered Binding pricing and the constant `fallback_policy`; catalog pricing is informational only and historical ProviderOperation receipts are preserved. |
| 20261024_0088 | Add partial indexes for unpublished outbox events, pending Director wakeups and queued NodeRuns; no execution identity or historical rows are rewritten. |
| 20261027_0089 | Add nullable non-secret `gateway_ref` JSON to existing connections and immutable revisions. Submitted/unknown management writes reconcile by fixed ID. Downgrade refuses any written reference; restore a verified snapshot with retained secrets instead of dropping history. |
| 20261027_0090 | Explicit media `auth_mode` on connections/revisions; bearer still requires its original credential, supported no-auth profiles require NULL. Availability uses NULLS NOT DISTINCT identity. Downgrade refuses retained no-auth revisions/evidence; no history is deleted or assigned a synthetic credential. |
| 20261028_0091 | Add a bounded ownership-only scanner for journaled Final Film uploads; reclamation keeps Artifact references and runs object IO outside database transactions. |
| 20261028_0092 | Add nullable `node_runs.next_attempt_at` and due-time filtering to the existing ownership-only queued resolver. Pending remote tasks release their lease and write the next Outbox event atomically. Frozen execution input, remote IDs and historical rows are unchanged. |
| 20261030_0093 | Extend the existing ownership-only Provider recovery resolver to discover committed synchronous image receipts without inventing remote task IDs. Receipt identity and stored-object hash are checked by the execution path; unknown submissions remain fail-stop. |
| 20261030_0094 | Add a partial expression index serving the `node_run.enqueue` Outbox dedupe lookup, so enqueue no longer scans a project's whole enqueue history. No table or data rewrite. |
| 20261030_0095 | Add the missing `shot_human_locks.shot_id` and `exports.episode_id` foreign keys (orphan rows are cleaned first), require workspace ownership in the two Provider availability RLS policies, verify both sides of `asset_tag_links`, drop the retired 2-argument recovery resolver, revoke UPDATE/DELETE on the rotation-audit and bootstrap-singleton tables, and add the NULL-project workspace-profile name index. |
| 20261007_0083 | Merge the model-system and local-media migration histories into one head without rewriting either branch. |
| 20261103_0096 | Normalize legacy tag keys with Python casefold, merge equivalent vocabulary rows within each project while preserving every asset link, and remove the derived key's display-length cap. Downgrade refuses keys that would be truncated. |
| 20261111_0097 | Link Agent Turns and messages to scoped threads; add Agent control fields and project-isolated tool-call receipts; exclude Agent Turns from Workflow recovery scans. |
| 20261113_0098 | Project-private source associations, immutable original revision identity, scoped extraction receipts and RLS; populated-source downgrade is blocked. |
| 20261113_0099 | Bounded pending-source discovery for the existing dispatcher, partial index and attempt fencing for late extraction results. |
| 20261117_0100 | I1 worktree: explicit project work type/goal/audience/duration/episode plan and ownership candidate keys; legacy type stays NULL, downgrade refuses populated intent. Upgrade/constraints/refused downgrade and empty-field rollback verified on isolated quality databases (I1-01); local runtime remains 0099 until an explicit rollout. |
| 20261117_0101 | Immutable source_extractions/source_fragments with schema-2 zero-based locators, processor evidence and extraction_schema_version; revisions gain the forward-only current_extraction_id and lose the legacy inline excerpts after a fail-closed conversion. Verified on isolated quality databases (I1-02): legacy conversion, blocked unknown locations, append-only grants, refused populated downgrade. |
| 20261117_0102 | Continuous-goal MasterRun, immutable accepted plans and control receipts (M02), plus the Turn master_run/plan_revision binding and the ProposalItem decision candidate key. Verified on isolated quality databases (I2a-01): project RLS, append-only plan/receipt grants, deferred origin FK refusing workflow turns, terminal/archive invariants, refused populated downgrade, alembic check clean. |
| 20261117_0103 | Trusted provider destinations and project egress policy with one mutable head (M03 part 1). Verified on isolated quality databases (I3-01): workspace-scoped destination RLS, project-scoped policy RLS, append-only revision grants, head-only UPDATE, head composite FK refusing another project's revision, refused populated downgrade, alembic check clean. Admission enforcement at real egress points remains I3-02. |
| 20261117_0104 | Source-use subjects, immutable declarations/revocations and artifact provenance (M03 part 2). Verified on isolated quality databases (I3-02): project RLS on all three tables, append-only declaration/provenance grants, subject pointer advancing while history stays readable, refused populated downgrade, alembic check clean. Admission enforcement itself lives in the access egress_admission port, not in this schema row. |
| 20261117_0105 | `artifact_reference_tokens.egress_admission` (nullable JSONB): new reference grants freeze the admission decision that allowed them; existing grants stay NULL and are never rewritten. Verified through the reference-issuance refusal tests and alembic check (I3-02). |

No canonical Project, Shot, Artifact, ProviderOperation, or EditSession is
deleted by these revisions. Revision 0070 backfills legacy Asset lifecycle and
tag data before enforcing the canonical constraints.

## Schema invariants

- Alembic has one worktree head: 20261118_0119 (verify with `alembic heads`; current local runtime remains 0099 until an explicit rollout).
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

当前实验唯一事实是 ExperimentBranch，HTTP 与 Director 共享创建服务。迁移
20261007_0084 已删除 production_experiments / shot_experiments，旧 ORM 也已移除；
该迁移在旧表非空时拒绝升级。需恢复的历史实例数据与证据独立保管，不能伪造成当前分支；
已明确弃用的环境按 DEVELOPMENT 的生命周期清理，不要求永久保留。
Golden fixture 使用当前 ExperimentBranch，不再为旧轨制造新样本。

## 数据库清理准入

当前只有 ExperimentBranch；旧实验 ORM、表和字段别名不属于当前业务。
清理迁移拒绝非空旧实验表，避免把旧引用误解释为正式引用。旧实例的数据卷和证据
保留在独立环境；新开发环境初始化当前 schema，不复用旧队列或补造冻结执行身份。
迁移不可降级。当前业务表、用户门、RLS、Artifact 血缘和显式授权约束仍须完整验证。

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

#### 镜头生成参数草稿（目标结构，未实现）

复用 `Shot.director_state` 的版本化结构，增加 typed `generation_settings` 子对象，
不新增 Shot 副本、参数表或独立运行实体。既有模型选择字段/Resolver 继续拥有选择权，
该对象中的合同身份仅用于校验参数来源，不构成另一套 Binding 选择。

| 语义字段 | 存储与约束 |
|---|---|
| 结构版本 | `schema_version`；缺省对象表示没有镜头参数覆盖，不给旧记录补造已设置值 |
| 阶段 | `image_keyframe` / `video`，各自拥有以下设置；不共享可变参数字典 |
| 输入模式 | `mode_id`；仅允许当前 Binding 与产品已开放模式；由同一保存字段供预检与执行读取 |
| 参数来源合同 | `source_contract_hash`；与当前解析合同比较，用于模型切换差异，不代替执行身份或资格 |
| 常用/模型参数 | `common_options` / `native_options` 的 typed 值；键、类型、范围、条件及可写性均由合同和适配器校验 |
| 可选提示词覆盖 | `prompt_override`；仅在合同明确存在可编辑覆盖槽时允许；原始 image/video prompt 分开保留 |

移除键表示恢复继承；显式 `0/false` 保持其类型，空字符串不能冒充任意数值或默认。
镜头覆盖优先于既有项目/Binding 有效配置，再取有证据的合同默认；来源解析复用现有
Resolver/Compiler，不新增项目参数配置体系。项目画幅继续属于 Project，阶段对象不能
以参数覆盖绕过项目画幅约束。计划时长属于 Shot，生成请求时长属于此生成设置，
实际媒体时长属于 Artifact，三者不自动互写。

通过既有镜头设计 Save 与 `expected_version` 原子保存本次设计字段和 generation_settings，
更新 Shot 版本；未修改的 voice、导演意图及其它已知字段须保留。JSON 扩展若不需数据库
DDL，则无需为此制造空迁移；若现有持久结构确需变更，仍走前向迁移并保持唯一 head。
更新全部当前调用方及生成类型，不保留第二套参数 DTO/旧写入通道。

#### 编译内容的冻结与受理

沿用已有计划/NodeRun 的冻结输入和 ProviderOperation 审计结构，补齐 schema version、
模型/合同/compiler/prompt 策略版本、输入版本、最终语义请求、转换报告、引用 hash/顺序
及已接受近似。具体列或 JSON 扩展在实现迁移中确定，不新建与生产事实竞争的任务表。
完整冻结范围见 MP-07；公共投影与发送私有数据分离，凭证仍只存引用和既有加密版本。

只读预览可持久化有过期/清理策略的非秘密快照或返回可核验的计划；受理时必须把可重放的
精确语义内容绑定到原 NodeRun。不能只存一个 hash，却在 Worker 用新合同重新编译。
同命令幂等重放与用户明确再次生成使用不同身份；唯一约束范围不能把所有相同 prompt
永久合并。请求授权、提交标记、远端 ID 与恢复证据继续附着在原执行链。

本切片选择“预览返回可核验计划，受理前确定性重建并比对，受理后冻结到原 NodeRun”方案，
不另建预览任务表。重建只为验证等价；任一 hash/版本不一致即拒绝，不能替换已确认内容。
冻结输入必须包含可发送的版本化语义请求和声明的传输槽，不仅是 UI 摘要；公共投影与私有
冻结内容来自同一次编译。Worker 仅把原 Artifact/凭证引用绑定到已声明传输槽，不重新选模、
取当前默认或重新映射参数。新代码不改变既有远端任务和历史 snapshot 的解释。

未保存草稿的浏览器恢复记录只保存字段 patch 和冲突比较所需基线，见 UI-11；它不是数据库
镜像、计划快照或执行授权。恢复后必须再次经过服务端读取、Save 和新预检。

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


<a id="director-agent-data"></a>
## Director Agent 数据扩展

迁移 0097 实现 Thread/Turn/Message 关联、Agent 控制字段和 `director_tool_calls`。
复用 Thread、Message、Turn、Invocation 和 Proposal，不新增 AgentSession 或模型调用日志。
工具审计受项目 RLS 和复合 FK 约束；唯一 (turn_id, call_id) 保存回执，
PROPOSE 的回执与 Proposal 同事务提交。输入版本保持冻结，后续从成功工具回执
合并 observed_versions，任何已观察对象版本改变均要求重新读取并另起轮次。

- Turn 已增加 thread_id、turn_kind(agent/workflow)、origin_agent_turn_id；Message 增加
  nullable turn_id 与 ordinal/idempotency linkage。历史关系不补造，原引擎绑定与
  checkpoint/submission 状态不改义。
- Agent 自己维护 agent_control_epoch、agent_lease_token、agent_lease_expires_at、
  stop_requested_at，不借用要求 graph runtime_execution_id 的 Workflow 控制记录。
  模型/工具调用数分别取自 Invocation/工具明细；计数缓存只能同事务更新。
- 受理事实不新增表：user Message + `status=queued` 的 Turn + `director.turn.accepted`
  Outbox 事件在同一事务提交。Turn.request_summary 冻结 `request`（规范化输入）、
  `input_hash`、`accepted_revision`、`limits`；intent/工具/技能/上下文快照在
  intent_snapshot。领取只改 Turn 自身：status、agent_control_epoch、agent_lease_token、
  agent_lease_expires_at、revision。因此同键重放可原样返回受理，不依赖当前模型配置。
- 0106 只新增/替换两个窄作用域 SECURITY DEFINER 扫描（`app.pending_agent_director_turns`
  与含 Agent lease 过期的 `app.recoverable_director_turn_contexts`），没有新表或平行写路径。
- 工具调用明细保存 turn/step/call_id、ToolSpec version/hash、脱敏参数、结果摘要/hash、
  observed_versions、latency、status/error；唯一键支持重放，沿用项目 FK、RLS 和索引。
  它不替代模型 Invocation，Agent/Workflow 不共同拥有同一 Turn 的状态写权。
- ThreadSummary 尚未实现，仅在摘要阶段加入，保存 source message range/hash、版本和 stale 标记；
  不复制 Shot、Model、Formal 等实时领域事实。CreativeDecision 优先复用既有提案决议，
  没有独立生命周期前不新增表。

实现时按当前迁移 head 直接演进未发布合同并更新全部调用方；保留历史数据，不生成
空迁移、平行兼容写路径或无消费者的预备表。完成/失败/取消/stale 沿用现有 Turn 状态；
blocked 只作结果/UI 分类，不扩展数据库 CHECK。

<a id="institution-schema"></a>
## 机构版完整Schema设计（D2设计审查通过，未实施）

依据PRODUCT D1合同、Owner O1–O7/N02–N04及第三轮P1/P4/P3候选。本文是数据合同唯一回填位置，
外部候选仅作为设计依据；D2数据结构已审查，仍须D3–D7细化执行/领域/API合同并在D8全量冻结。
**D8之前不能据此创建迁移；D2通过不是数据库或产品测试通过。**
现有ORM、历史迁移仍表示当前实现。当前实例不可达，以下所有新表/列均为目标。

### D2设计范围与现有事实差异

| 需求域 | 当前实际事实 | 目标处置 |
|---|---|---|
| 项目/三作品 | Project无独立作品类型；genre/style是创意档案 | EXTEND Project类型/目标，保留既有档案 |
| 资料 | ProjectFile/Revision、原件、attempt、excerpts JSON | EXTEND/REFACTOR不可变解析快照与定位；不把excerpts当研究 |
| 研究 | 无ResearchResult/修正历史 | NEW有效结果指针、不可变修订与引用 |
| 独立文化知识 | 无发布/引用实体 | NEW同用户跨Workspace知识与显式发布内容、项目固定引用；私有来源独立受限 |
| 资产 | Asset/Version/Reference全项目归属 | EXTEND公共发布/固定引用/变体，保留唯一版本和Artifact血缘；尚须D2/D5安全闭合 |
| 目标/流程 | Turn已有，MasterRun/BusinessFlow未有 | NEW第三轮两业务表+控制回执、Flow三表，精确FK及状态规则回填待完成 |
| 外发 | egress为网络守卫，没有项目策略 | NEW第三轮策略revision/head和目的地revision；准入复用Invocation/Operation |
| 生产/编辑/交付 | 原Graph/NodeRun/Operation/Artifact、EditSession/Export | REUSE；分集交付作用域和正式完成条件需显式扩展，不加第二生产事实库 |

D2当前批次已实际读取access/models、assets/models、production/models、execution/models的相关实体、
Turn模型、0098迁移、RLS上下文/发现，以及P1/P4全稿和P3准入字段。
Project仍含budget_limit/budget_currency历史字段；新机构设计不增加金额预算/余额/积分，
旧列是否还有消费者需定向追踪再定处置，不在本批顺便删除。

### 新增表通用合同

以下N=NOT NULL，?=NULL；未写默认的字段不默认填空。UUID由应用uuid4生成，时间timestamptz。
JSON使用JSON_DOCUMENT（PG JSONB），哈希CHAR(64)小写hex，序号Integer>0，行版本Integer default1>0。
所有id PK；created_at N server now()；created_by UUID N FK users.id RESTRICT；这三列仅在下表声明“公共列”时继承。
所有不可变修订运行角色只获SELECT/INSERT，撤UPDATE/DELETE/TRUNCATE且检查继承角色/owner。
应用/Worker不得是迁移owner、superuser或BYPASSRLS。管理员仍可改DB，不宣称REVOKE限制管理员。
FK默认RESTRICT，循环指针用DEFERRABLE INITIALLY DEFERRED NO ACTION，不能用复合SET NULL误清父身份。

项目表FORCE RLS，USING/WITH CHECK精确project_id=app.current_project_id()，设置GUC前先鉴权。
共享知识/公共发布表FORCE用户RLS，owner_user_id=app.current_user_id()；源/消费Workspace必须由此用户拥有。
新增workspaces(id,owner_user_id)候选键，跨空间复合FK验证同owner；Provider目的地声明仍为Workspace RLS。
项目私有表继续项目RLS，同用户不能通过公共查询读取私有研究。沿现有access，不新增复杂RBAC。无GUC拒绝，Worker归属从DB窄发现函数获取，
不能信队列JSON。不可变表的可见性仍受其当前所属对象/引用授权限制。
所有查询有分页上限；记录内容不放通用EventLog、普通错误日志或未过滤的全局检索索引。

### 项目与分集（R01/R13/R33–R35）

projects增加：
- work_type String(32)?，CHECK NULL或animation_promo/single_comic/serial_comic；旧项目保持NULL，不凭旧genre推断；
  新机构项目保存必须选择一种，旧项目显式选择后才能走机构自动流程。NULL不是第四种产品。
- creative_goal Text N default ''，audience Text N default ''；保存长度上限分别16000/2000；
  固定CHECK数据库亦限制长度。Project.version覆盖这些字段CAS，更新同事务发ProjectChanged。
- planned_duration_seconds Numeric(12,3)? CHECK>0；planned_episode_count Integer? CHECK>0，
  single_comic必须为1或未填写，serial_comic若填写须>=2；宣传片不设置集数计划。
  计划时长不代表模型实际时长，片长参数不移入金额字段。
  此字段为项目整体时长意图（连续剧也是总体目标），不代替分集或镜头计划；0100有新意图值或project_changed事件时拒绝降级。

增加UNIQUE projects(id,workspace_id)，供跨域身份FK；Episode继续一项目多集，单集类型API/服务限制仅一集，
并发创建锁Project，禁止仅先count再insert。类型变化锁Project并检查现有集/正式结果，返回影响，未经用户确认不删。
现有Episode(project_id,episode_number)唯一；Scene/Shot父子关系继续复用，跨项目复合FK与逐集导出见本文件分集及迁移合同。
Story通过typed Proposal/ScriptDocument现有事实，不新建独立可变Story镜像表。

### 不可变解析与来源（R02–R07/R10）

原件不迁移所有权。project_files/file_revisions保持，增加Revision UNIQUE(id,file_id,project_id)。
现有status/attempt继续拥有处理控制；新解析表是成功内容快照，不新建任务状态机。
解析Worker先读原件，离开事务本地解析，再以revision attempt+当前关联资格比较写入；
过期/解除关联不推进当前解析指针。已创建成功快照永不重写。

| 表 | 列及默认 | 键/约束/索引 |
|---|---|---|
| source_extractions | 公共列；project_id/file_id/file_revision_id UUID N；attempt Integer N>0；parser_key/parser_version String(80) N；content_hash CHAR64 N；extraction_schema_version Integer N>0；coverage JSONB object N；completed_at timestamptz N | UNIQUE(file_revision_id,attempt)、UNIQUE(id,file_revision_id,project_id)；FK(file_revision_id,file_id,project_id)→project_file_revisions(id,file_id,project_id)；索引(project_id,file_revision_id,created_at,id) |
| source_fragments | id UUID PK；project_id/extraction_id/file_revision_id UUID N；ordinal Integer N>=0；locator_kind String(24) N；locator JSONB object N；text_content Text N default ''；content_hash CHAR64 N；created_at N now() | UNIQUE(extraction_id,ordinal)、UNIQUE(id,file_revision_id,project_id)；FK(extraction_id,file_revision_id,project_id)→source_extractions(id,file_revision_id,project_id)；CHECK locator_kind合法；索引(project_id,file_revision_id,ordinal) |

locator_kind=paragraph/page_region/image_region/time_range/table_cells；具体locator typed schema在D4冻结，
至少保留起止段/页与归一化区域、毫秒时间段、sheet及行列范围。coverage包含处理总量/已处理量/遗漏及原因，
不能在部分覆盖时标全量完成。限制校验在数据库检查JSON种类与服务typed校验两层，不声称JSON跨表有FK。

project_file_revisions增加current_extraction_id UUID?，复合FK(current_extraction_id,id,project_id)
→source_extractions(id,file_revision_id,project_id)延迟NO ACTION。当前指针仅处理CAS更新；
成功重新解析形成新Extraction及Fragments，旧研究引用仍指旧Fragment。

现有excerpts/parser_version作为当前唯一提取实现需要一次性迁移到新快照后移除旧写入/消费者，
不长期双写。迁移只对实际parsed且有结果的旧修订构建带legacy parser标记的既有提取快照，
保留原文本/定位/hash；不得伪造研究、模型调用或覆盖度。无法证明定位的记录标明legacy locator限制，
不伪造页码。D7确定逐字段转换与有数据降级阻断条件。此处是迁移设计，未执行。

### ResearchResult与用户修订（R06–R09/R24）

ResearchResult是一个稳定研究条目；ResultRevision是其不可变内容快照。
当前有效版本只由Result.current_revision_id指向，AI候选、用户保存、历史恢复都是revision，
不另建一套user_override正文。六类kind=summary/person/place/event/timeline/cultural_clue。
同名人物或地点不自动合并；无来源条目必须标unverified，不虚构Citation。

| 表 | 列及默认 | 键/约束/索引 |
|---|---|---|
| research_results | 公共列；project_id UUID N；kind String(24) N；current_revision_id UUID?；version Integer N default1；archived_at timestamptz? | CHECK kind六值；UNIQUE(id,project_id)；索引(project_id,kind,archived_at,id)；project FK RESTRICT |
| research_result_revisions | 公共列；project_id/result_id UUID N；number Integer N>0；origin String(16) N；body JSONB object N；content_hash CHAR64 N；verification String(16) N default unverified；base_revision_id UUID?；restores_revision_id UUID?；accepts_revision_id UUID?；applied_result_version Integer?>1；origin_invocation_id UUID?；output_item_key String(120)?；request_key String(160) N；request_hash CHAR64 N | UNIQUE(result_id,number)、UNIQUE(project_id,request_key)、UNIQUE(id,result_id,project_id)、UNIQUE(id,project_id)、UNIQUE(result_id,applied_result_version)、UNIQUE(id,result_id,project_id,applied_result_version)；FK(result_id,project_id)→research_results(id,project_id)；部分UNIQUE(origin_invocation_id,output_item_key) WHERE origin_invocation_id IS NOT NULL；索引(project_id,result_id,number) |
| research_citations | id UUID PK；project_id/research_revision_id/source_fragment_id/file_revision_id UUID N；claim_key String120 N default root；locator_override JSONB object?；quoted_text Text N default ''；created_at N now() | UNIQUE(research_revision_id,claim_key,source_fragment_id)；FK(research_revision_id,project_id)→research_result_revisions(id,project_id)；FK(source_fragment_id,file_revision_id,project_id)→source_fragments(id,file_revision_id,project_id)；索引(project_id,file_revision_id,research_revision_id) |

Result.current_revision_id复合FK(current_revision_id,id,project_id)→Revision(id,result_id,project_id)延迟。
延迟约束触发器校验所指revision.applied_result_version非空且不大于Result.version；不能指向未应用候选。
归档也可增加Result.version，不强制其始终等于历史内容受理版本，否则单独归档会破坏指针FK。
另有转换触发器：current指针改变时NEW.version=OLD.version+1，所指修订applied_result_version必须
等于NEW.version且base_revision_id与原current一致；仅元数据归档保持原指针时才允许较旧applied版本。
因此不能直接把current拨回旧revision来冒充恢复；恢复必须新增revision。
base/restores分别复合FK(base_revision_id,result_id,project_id)与(restores_revision_id,result_id,project_id)→Revision同候选键。
accepts复合FK(accepts_revision_id,result_id,project_id)→Revision同候选键。
origin=user/model/restore/accept，CHECK model必有invocation及output_item_key，非model二者均NULL；
restore必有restores_revision_id，其余必须NULL；accept必有accepts_revision_id，其余必须NULL。
user/restore/accept必须applied_result_version非空，model首次直接生效时非空，其余候选为NULL。
verification=unverified/corroborated/user_asserted；
AI不得写user_asserted；corroborated表示有多来源支持而非系统保证史实正确，来源条件服务校验。

origin_invocation_id与project_id复合引用director_invocations(id,project_id)，先核对/补父候选键。
调用失败不生成有效ResultRevision；调用回执仍由Invocation拥有。
同Invocation输出重放先校验output_item_key+内容hash，匹配返回原revision，不重复建条目。
后续分析针对已有Result必须显式提供result_id/base_revision，不能用名字猜配。

用户保存锁Project→Result，先查request_key/hash原回执，再CAS expected_version；追加revision+citation、更新current指针/version、
Outbox同事务。研究编辑无需Proposal。首次AI结果可设current；已有有效结果上的再分析只追加候选，
不更新current（即使尚无人编辑也先显示差异，避免用户正在读取的依据静默变化）。
用户显式采纳候选后在同一CAS事务复制其内容/引用形成origin=accept新revision，再推进current；不改候选行。
新行的applied_result_version=原Result.version+1，并作为本次受理回执保留，后续再有修改也能读回原受理版本。
恢复复制所选历史内容及引用形成origin=restore新revision，
记录base=current/restores=所选历史，不倒拨版本。同request_key+hash重放返回原决定，异hash409。

引用有效性由文件关联/修订及当前限制计算，不能重写历史citation把它换成新来源。
解除关联使引用标unavailable；原件常规读取仍拒绝，历史研究修订可按项目权限查看。
结果archived只影响常规检索，不删除恢复历史；硬删除引用链必须单独维护授权。

body按kind强类型：summary含摘要段与覆盖说明；person/place含显示名/别名/描述；
event含事件描述与时间不确定性/相关人物地点引用；timeline为有序项，允许unknown与区间；
cultural_clue含主题/解释/与资料关联。具体schema与跨条目关系在D4完成，
当前不允许任意JSON执行逻辑或将LLM文本转成SQL。

I4-02已实施（迁移0110）：三表、复合候选键、延迟FK、origin/verification/应用版本CHECK、
`app.research_result_current_guard()`（指针只能指向同结果已应用修订、版本恰+1、base等于原current；
仅元数据归档允许版本不变或+1）与RLS/追加只读授权。六类判别形状在`app/assets/research_bodies.py`
（schema_version=1，多余字段拒绝）；引文逐字与locator范围在服务层校验。
I4-02b已实施（迁移0111）：`research_analyses`/`research_analysis_invocations`/`research_analysis_results`
三表与`project_file_revisions.current_analysis_id`（延迟复合FK、项目RLS、仅SELECT/INSERT）；
发布服务先校验六类outcome（恰六类、findings计数一致、none无输出、incomplete必须有原因）与全部引文，
再写清单/结果修订/链接，失败不留部分修订；`origin=model`修订只以候选（applied_result_version=NULL）
或新结果首次生效两种形态出现，分析指针不覆盖ResearchResult.current。
search_text投影与pg_trgm/GIN索引随I4-03实施：`app.research_search_text_v1`/`app.knowledge_search_text_v1`为IMMUTABLE函数，revisions上的`search_text`由BEFORE INSERT触发器确定性写入（可移植测试库无法编译PostgreSQL生成列，故以触发器维护同一派生投影；应用不直接写该列），PG建立`gin_trgm_ops`索引；研究列表`q`在PostgreSQL使用search_text，SQLite仍为参数化body匹配。

### 独立文化知识（R11，Owner N02）

知识业务归属当前用户（N05），跨该用户所有Workspace，不要求Project。创建workspace仅保留来源身份。
已发布内容是显式选定的不可变快照，
与项目研究各有独立生命周期；项目研究继续是私有事实，知识修订不能回写研究。
首期不创建机构多角色审批平台。新表：

| 表 | 列及默认 | 键/约束/索引 |
|---|---|---|
| knowledge_entries | 公共列；owner_user_id/workspace_id UUID N；kind String24 N；current_revision_id UUID?；publication_status String16 N default draft；version Integer N default1；withdrawn_at timestamptz? | FK(workspace_id,owner_user_id)→workspaces(id,owner_user_id) RESTRICT；UNIQUE(id,owner_user_id)；kind六类，status draft/published/withdrawn；withdrawn与时间非空等价；索引(owner_user_id,publication_status,kind,id) |
| knowledge_revisions | 公共列；owner_user_id/entry_id UUID N；number Integer N>0；title String240 N；body JSONB object N；content_hash CHAR64 N；allowed_uses/public_source_notes JSONB array N；operation/publication_status String16 N；expected_entry_version Integer N>0；result_entry_version Integer N>1；request_key String160 N；request_hash CHAR64 N | UNIQUE(entry_id,number)、UNIQUE(owner_user_id,request_key)、UNIQUE(id,entry_id,owner_user_id)、UNIQUE(id,owner_user_id)、UNIQUE(entry_id,result_entry_version)；FK(entry_id,owner_user_id)→entries(id,owner_user_id)；CHECK result_entry_version=expected_entry_version+1；索引(owner_user_id,entry_id,number) |
| knowledge_source_links | id UUID PK；project_id/workspace_id/owner_user_id/research_revision_id/knowledge_revision_id UUID N；created_at N now() | 项目RLS；FK(project_id,workspace_id)→projects(id,workspace_id)；FK(workspace_id,owner_user_id)→workspaces；FK(research_revision_id,project_id)→research_result_revisions(id,project_id)；FK(knowledge_revision_id,owner_user_id)→knowledge_revisions(id,owner_user_id)；UNIQUE(knowledge_revision_id,research_revision_id) |
| project_knowledge_references | 公共列；project_id/workspace_id/owner_user_id/knowledge_entry_id/knowledge_revision_id UUID N；allowed_use String40 N；version Integer N default1；detached_at timestamptz? | 项目RLS；FK(project_id,workspace_id)→projects；FK(workspace_id,owner_user_id)→workspaces；FK(knowledge_revision_id,knowledge_entry_id,owner_user_id)→knowledge_revisions(id,entry_id,owner_user_id)；UNIQUE(project_id,knowledge_revision_id,allowed_use)；索引(project_id,detached_at,id) |

entries.current FK(current_revision_id,id,owner_user_id)→knowledge_revisions(id,entry_id,owner_user_id)延迟。
operation=save_draft/publish/withdraw；revision.publication_status为本次决定后的draft/published/withdrawn，
分别由operation固定映射，数据库CHECK，不允许任意组合。保存新草稿不会覆盖当前已发布版本：
当前published时修改内容以新publish操作明确确认后更新；编辑草稿在浏览器恢复，不悄悄撤下已发布内容。
每次决定锁Entry，先重放request_key+hash回执，再CAS expected_entry_version，追加完整revision+私有源链接，
更新Entry的current/version/status/withdrawn_at及事件同事务。withdraw复制当前内容为不可变撤回修订，
不是物理删除。Entry状态为当前revision的投影，受写入口及约束触发器保护，禁止独立更新不留决定。
Entry current变化必须NEW.version=OLD.version+1，revision.expected_entry_version=OLD.version、
result_entry_version=NEW.version且publication_status相同；不同owner/entry由复合FK拒绝。
重放返回原result_entry_version与当时publication_status，不能以现在head冒充原响应。
知识所属用户可编辑草稿；发布或纠正需明确确认具体内容快照及允许用途，不能AI自动推进published。
新版本发布使current前进，项目已引用版本不跟随；撤回锁Entry并写状态/版本/事件，阻断新引用；
已有引用保留但在上下文/新生产资格中标撤回，不能只靠引用时的旧检查。

knowledge_source_links仅原项目有权读取，不通过跨项目知识DTO序列化；跨项目查询只返回显式发布的安全
public_source_notes与内容，不暴露私有source id、object_key、引用签名或完整摘录。
手工录入允许无source_link，标明用户提供。发布项目研究内容需服务端检查源项目所属用户与知识owner相同且源许可有效，
不可把public_source_notes当未校验的任意URL抓取指令。
新引用/发布/撤回与来源限制的线性化、多个原项目引用同一知识的处理在D4/D5完成安全交叉检查。

知识内容索引复用PostgreSQL可用文本查询，先只索引已发布可见快照；索引是可重建投影，不是第二事实源。
是否引入额外中文分词/向量设施必须有检索证据，当前未引入新基础设施。


### 公共生成资产与项目固定引用（R14–R18，目标未实施）

Owner N05已确认同一用户所有Workspace共享。下表owner_user_id是共享权限边界，
workspace_id在Publication/Item是源空间，在ProjectLink是消费空间，二者允许不同但必须同owner。
私有源表RLS不变；不得把此共享扩展为其他用户可见或共享原件。

已读取AssetFromArtifactService、AssetCardReadService、references API、WorkbenchExecution引用编译及
reference_delivery：当前均要求源版本/Artifact与消费项目相同。因此“新增公共库页面”不能实现跨项目复用；
必须完整改造授权投影和所有引用消费者，不能删除project_id检查来放开任意源对象。

本设计保留Asset/AssetVersion/AssetVersionReference/Artifact的原项目所有权。
公共库记录是被采用版本的**发布资格与安全展示投影**，不是第二套资产版本/媒体生产事实。
纯引用只创建项目链接，不复制AssetVersion/Artifact；真正修改形成项目自己的AssetVersion变体。
源项目删除采用归档；仍被发布/引用的版本与Artifact受RESTRICT保护，不能CASCADE销毁。

| 表/扩展 | 字段 | 约束与可变性 |
|---|---|---|
| public_asset_publications | 公共列；owner_user_id/workspace_id/source_project_id/source_asset_id/source_asset_version_id UUID N；safe_name String160 N；safe_description Text N default ''；safe_metadata JSONB object N；publication_hash CHAR64 N；status String16 N default available；revision Integer N default1；withdrawn_at timestamptz? | UNIQUE(source_asset_version_id)、UNIQUE(id,owner_user_id)、UNIQUE(id,source_asset_version_id,owner_user_id)；FK(workspace_id,owner_user_id)→workspaces；源Project+Workspace、Asset/Version精确FK；status available/restricted/withdrawn；payload/源身份不可变，仅状态/revision可更新；用户RLS |
| public_asset_publication_items | id UUID PK；publication_id/owner_user_id/workspace_id/source_project_id/source_asset_version_id/source_reference_id/artifact_id UUID N；created_at N now() | FK(publication_id,source_asset_version_id,owner_user_id)→publications；FK(source_reference_id,source_asset_version_id,artifact_id,source_project_id)→AssetVersionReference；UNIQUE(publication_id,source_reference_id)、UNIQUE(id,publication_id,artifact_id,owner_user_id)；仅SELECT/INSERT；用户RLS |
| project_public_asset_links | 公共列；project_id/workspace_id/owner_user_id/publication_id/source_asset_version_id UUID N；local_label String160 N default ''；version Integer N default1；detached_at timestamptz?；request_key String160 N；request_hash CHAR64 N | FK(project_id,workspace_id)→projects；FK(workspace_id,owner_user_id)→workspaces；FK(publication_id,source_asset_version_id,owner_user_id)→publications；UNIQUE(project_id,publication_id)、UNIQUE(project_id,request_key)、UNIQUE(id,project_id,publication_id,source_asset_version_id)、UNIQUE(id,project_id,publication_id,owner_user_id)；项目RLS；源版本不可改，仅label/detach/version可改 |
| AssetVersion扩展 | base_publication_id/base_public_asset_link_id UUID? | 两列同空/同非空；FK(base_public_asset_link_id,project_id,base_publication_id)→project_public_asset_links(id,project_id,publication_id)，补父候选键；仅创建真实变体时写；保持本项目Asset所有权，不因镜头表情姿势自动建全局版本 |

新增父候选键assets(id,project_id)、asset_versions(id,asset_id,project_id)、
asset_version_references(id,asset_version_id,artifact_id,project_id)。publication的源版本复合FK
(source_asset_version_id,source_asset_id,source_project_id)→asset_versions；源项目与workspace用projects复合FK。
publication_items的source_project与publication源project一致由增加
UNIQUE(publications.id,source_project_id,source_asset_version_id,workspace_id)及对应四列FK保证，
不能仅凭服务相信客户端源项目。

同时为AssetVersionReference补精确源版本/Artifact项目FK，父键asset_versions(id,project_id)、
artifacts(id,project_id)；迁移前检查既有数据，存在错配阻断且保留原记录，不自动搬数据。
这样publication item不能通过既有宽松单列FK夹带另一项目私有Artifact。

ShotReferenceBinding增加public_asset_link_id UUID?、publication_id UUID?；
二者同空/同非空；非空时resolution_mode必须pinned_version、asset_version_id非空、asset_id NULL，
用(public_asset_link_id,project_id,publication_id,asset_version_id)复合FK→project_public_asset_links。
纯公共引用仍指同一原AssetVersionReference，编译必须通过链接解析其publication_items，
不构造另一张target项目AssetVersionReference。原项目私有路径继续精确同项目核验。
引用具体Artifact必须存在于该publication_items；序号和用途仍来自绑定/原reference，不信客户端排序。
实验分支继续是当前项目，不随公共链接跨项目。

AssetFromArtifact用户采纳生成资产的事务扩展为Asset/Version/Reference+Publication/Items+Outbox原子提交。
仅用户实际采用的AI生成版本触发，不把普通上传原件、所有候选或失败任务自动发布。
safe_metadata采用明确白名单，不复制prompt、完整研究、原件下载地址、连接/凭据、全部metadata。
存在使用限制时仍登记库记录并显示restricted及安全原因，不能删掉限制来满足“自动入库”。
publication_hash包含固定版本/成员/安全展示/初始限制依据；同版本重复采用读原记录，内容不符报冲突。
更改已发布内容新建AssetVersion再发布；单纯撤销/限制更新只改资格，保留原内容与引用。

公共浏览仅提供安全投影；原Asset/Version/Artifact RLS不因public=true而全表放开。
后端新增窄授权读取端口，输入当前project/link/item/purpose，验证当前用户/Workspace、链接未解除、
publication可用、来源限制、媒体状态和固定版本后返回最小内部媒体描述。
PG实现沿既有窄函数模式，固定search_path、REVOKE PUBLIC、严格作用域、只返回批准字段，
不提供任意project_id的绕过读取函数；普通SELECT仍拒绝私有源项目。所有拒绝用例须真实受限角色测试。
该端口是已批准跨项目公共资产访问的权限执行点，不授予NodeRun、Invocation、ProjectFile等源事实访问。

必须同步的消费者：公共列表/卡片、references的写入与resolve、WorkbenchExecution的hydrate/顺序/指纹、
所有媒体实际发送处、reference token签发/下载、候选预览与权限下载。不能只在UI绕过所有权。
冻结计划包含public link/publication/item/版本及限制版本；发送前重验，撤销使旧计划不可新提交。
对已发送任务仅保留原身份恢复，不撤回已发数据，不以撤销为由重提。

ArtifactReferenceToken保持project_id/workspace_id为源Artifact归属，新增六个nullable UUID：
consumer_project_id、consumer_workspace_id、owner_user_id、public_asset_link_id、publication_id、publication_item_id。
六列全空为旧同项目入口，六列全非空为公共入口，不允许部分NULL绕过复合FK。
源与消费项目分别保留，不把生产Artifact改挂目标项目。公共入口增加以下RESTRICT FK：
- (consumer_project_id,consumer_workspace_id)→projects(id,workspace_id)；
- (consumer_workspace_id,owner_user_id)→workspaces(id,owner_user_id)；
- (publication_id,project_id,workspace_id,owner_user_id)→public_asset_publications(id,source_project_id,workspace_id,owner_user_id)，补此候选键；
- (public_asset_link_id,consumer_project_id,publication_id,owner_user_id)→project_public_asset_links(id,project_id,publication_id,owner_user_id)；
- (publication_item_id,publication_id,artifact_id,owner_user_id)→public_asset_publication_items(id,publication_id,artifact_id,owner_user_id)；
- (artifact_id,project_id)→artifacts(id,project_id)，防单列artifact引用夹带其他私有对象。

token表RLS仅对精确消费授权增加分支：consumer_project_id=current_project且owner=current_user、
上述关联完整；不放开源Artifact/Project/研究表。旧路径仍要求project_id=current_project。
INSERT约束触发器/服务检查link未解除、publication可用、源限制、当前外发准入与creator：
created_by_run_id须属于COALESCE(consumer_project_id,project_id)，或created_by_user_id等于当前认证用户；
仍满足原creator二选一。不能仅验证FK存在就忽略撤销资格。
运行角色只SELECT/INSERT token，禁止修改六列/源身份/admission；到期/撤销由有效资格读取拒绝，不重写历史证据。
签发与下载均使用同一窄资格端口，不为读取源媒体把请求事务GUC切成源项目。原公开token解析函数
按hash、有效期、原Artifact可用性及公共链接/当前限制复核，只返回这一项允许的bytes元数据。
实际外发准入归消费项目及其Workspace的目的地；源项目许可不能替代消费项目许可，来源用途限制仍须同时满足。
索引token(consumer_project_id,expires_at,id) WHERE consumer_project_id IS NOT NULL、(publication_id,expires_at)。
不得把生成源Artifact的NodeRun改挂消费项目，也不得只因知道Artifact ID签发公共URL。

索引：publications(owner_user_id,status,safe_name,id)，items(publication_id,id)，
links(project_id,detached_at,id)及(publication_id,project_id)，AssetVersion(base_publication_id)部分索引。
引用/撤销资格检查使用同一确定锁序，D3/D5协调避免按源/目标不同顺序锁项目形成死锁。
库记录、令牌组合键、NULL组合及资格竞态已交叉设计，实际出口合同见MODEL_PROVIDER/API；未宣称已实施或通过PG验证。


### 持续目标、计划与控制回执（R20/R22/R28–R32）

承接第三轮P1，保留其来源Agent Turn、专用回执、服务端verify、复合FK、原Turn状态不改义等修订。
以下回填目标数据合同；无新通用AgentRun/Task/Approval表。P1仅有单镜头predicate不足全产品完成条件，
扩展注册合同在D3冻结，不允许客户端布尔值或自由表达式判定完成。

| 表 | 字段与默认 | 唯一/索引/主要检查 |
|---|---|---|
| director_master_runs | id UUID PK；project_id/workspace_id/actor_id/source_thread_id/origin_turn_id UUID N；origin_turn_kind String16 N default agent；goal Text N；current_plan_id UUID?；status String24 N default planning；desired_state String16 N default run；wait_reason String80?；control_epoch Integer N default0；revision Integer N default1；deadline_at/finished_at/archived_at timestamptz?；created_at/updated_at N now() | UNIQUE(id,project_id)、UNIQUE(id,project_id,workspace_id,actor_id)、UNIQUE(project_id,origin_turn_id)；goal去空白1..16000、origin_kind=agent、epoch>=0/revision>0；索引(project_id,status,updated_at,id)、(source_thread_id,created_at,id)，非终态deadline/updated_at部分索引 |
| director_master_run_plans | id UUID PK；project_id/master_run_id UUID N；revision Integer N>0；schema_version String80 N；plan_hash CHAR64 N；plan_data JSONB object N；decision_ref UUID N；created_by_turn_id UUID?；created_by_actor_id UUID N；created_at N now() | UNIQUE(master_run_id,revision)、UNIQUE(id,master_run_id,project_id)、UNIQUE(master_run_id,revision,project_id)、UNIQUE(id,revision,master_run_id,project_id)、UNIQUE(project_id,decision_ref)、UNIQUE(master_run_id,plan_hash)；不可变；索引(project_id,master_run_id,created_at,id) |
| director_master_run_control_receipts | id UUID PK；project_id/master_run_id/actor_id UUID N；operation String16 N；expected_revision Integer N>0；request_hash CHAR64 N；result_revision Integer N；result_data JSONB object N；created_at N now() | operation pause/resume/cancel/verify；result_revision=expected_revision+1；UNIQUE(master_run_id,expected_revision,operation)；不可变；索引(project_id,master_run_id,created_at,id) |

Run八态planning/running/waiting/paused/stopping/succeeded/failed/cancelled；
desired_state run/pause/cancel。DB CHECK终态与finished_at非空等价，finished_at>=created_at，
deadline不早于created_at；archived_at非空只允许终态且不早于finished_at。
父actor→users RESTRICT，project/workspace复合FK→projects RESTRICT；
来源Thread(source_thread_id,project_id)→director_threads(id,project_id)延迟NO ACTION；
来源Turn(origin_turn_id,project_id,workspace_id,actor_id,source_thread_id,origin_turn_kind)
→director_turns(id,project_id,workspace_id,actor_id,thread_id,turn_kind)延迟NO ACTION，新增对应候选键。
非空Thread与agent常量阻止threadless/workflow Turn利用NULL跳过FK。

Plan(master_run_id,project_id)→Run(id,project_id)，Run(current_plan_id,id,project_id)
→Plan(id,master_run_id,project_id)均延迟NO ACTION；Receipt(master_run_id,project_id)→Run同键。
Plan(decision_ref,project_id)→ProposalItem(id,project_id)；补ProposalItem候选键；
(created_by_turn_id,master_run_id,project_id)→Turn(id,master_run_id,project_id)，creator可空，Run归属仍强制。

Turn新增master_run_id UUID?、plan_revision Integer?、business_flow_step_attempt_id UUID?。
FK(master_run_id,project_id)→Run；(master_run_id,plan_revision,project_id)
→Plan(master_run_id,revision,project_id)；plan_revision非空要求Run非空且>0。
UNIQUE Turn(id,master_run_id,project_id)及(id,master_run_id,plan_revision,project_id)；
Run关联索引(master_run_id,created_at,id) WHERE master_run_id IS NOT NULL。
不修改原request_key、scope、引擎、Turn八态/20合法边，不提前删除agent lease，不改turn_kind。

plan_data固定顶层goal/flows/dependencies/completion/input_versions/limits/decision_basis，后续版本支持supersedes_plan_id/
change_reason与flow_dispositions。hash规范化schema_version及完整payload：排序对象键、数组顺序保留、
UUID小写、UTC、禁止NaN。相同Run/hash重放原计划，不靠nonce绕去重。
decision_basis={expected_run_revision:int>=1,expected_control_epoch:int>=0,current_plan_id:UUID|null,
current_plan_revision:int|null}，后两项同空；均为生成计划时已观察并核验的真实Run状态，进入plan_hash。
创建待确认Plan/Proposal不推进Run.current/status/revision（初始保持planning，已有计划保持原控制状态），
避免创建候选本身使其CAS依据立刻过期。内部heartbeat/监督槽读取也不无故增加业务Run.revision。
Pause/Resume/verify等控制使旧basis失效时，重新预览须核验全部来源/Flow disposition并形成新Plan revision，
新的真实basis自然形成新hash；不能只换nonce或在Apply时偷偷改expected_revision。
同一basis+相同内容的重复请求仍回原Plan，解决“同内容去重却永久卡在旧CAS”的冲突。
limits为模型调用/工具/步骤/时间/并发/生产操作次数，无金额字段；跨Turn累计从原Invocation/工具/attempt/
Operation事实计算，缓存不得独立决定可新发数量。input_versions绑定研究/知识/脚本/资产/策略所用版本。

建立目标先经现有接纳路径获得合法Agent Turn，同事务建Run并绑定origin；不重跑origin、不篡改状态。
Plan追加与单项typed Proposal同事务，确认用director.master_run_plan_apply写Run.current_plan_id、
epoch/revision和ProposalItem决定/Outbox；Plan不可UPDATE。
控制锁Project→Run，先查(operation,expected_revision)回执，hash相同返回原result_data，异载荷409；
再CAS状态并revision+1，回执/事件一起提交。成功no-op也留回执；非法状态与权限失败无写入。
verify事实未满足是已受理的核对，保留结果回执，但不把Run改成功。当前GET不写。
普通问答/查询不建目标；origin禁止后续接口重新绑定；关联Turn一个目标至多一次。

三表项目FORCE RLS；Run运行角色SELECT/INSERT/UPDATE，Plan/Receipt仅SELECT/INSERT；
均不授DELETE/TRUNCATE。这里采用RESTRICT/延迟NO ACTION保留已有关联事实，不复制旧候选的
项目CASCADE来规避项目归档/公共引用保护。该处是可回滚设计细化，不授权维护删除；
项目真实硬清理始终需单独批准与依赖审查。

### BusinessFlow跨Turn数据合同（R21/R23/R30）

**状态：三表已由迁移0107实施**（列/键/RLS/部分唯一槽与下列合同一致；读投影HTTP仍未实施）。

Definition是版本化代码注册项，不建表：key/version/contract_hash、输入输出schema、state_schema_version、
step_specs、completion_rule_ids、resume_rule_id、graph_entrypoint。只注册Python LangGraph入口；
不接受客户端函数名/动态import，不解释任意JSON DAG，不新增Run/Flow根checkpoint。
数据库保存冻结实例与交接，Graph执行逻辑仍在原Director Runtime。

三表共同id UUID PK、project_id UUID N FK projects RESTRICT、revision Integer N default1>0、
created_at/updated_at N now()、status String32 N、wait_reason/terminal_reason String80?、
finished_at timestamptz?。终态与finished_at非空等价；terminal_reason终态必填/非终态NULL；
wait_reason仅非终态；finished_at>=created_at。FORCE项目RLS，运行SELECT/INSERT/UPDATE，
撤DELETE/TRUNCATE；冻结身份列触发器只允许指定状态/回执字段改变。

| 表 | 追加字段 | 键/索引 |
|---|---|---|
| director_business_flow_instances | supervisor_run_id/plan_id UUID N；plan_revision Integer N>0；flow_key String120 N；definition_key String120 N；definition_version String80 N；contract_hash/input_hash CHAR64 N；input_data JSONB object N；scope_type String24 N；scope_entity_id UUID N；created_by_turn_id UUID?；status default pending | UNIQUE(supervisor_run_id,plan_id,flow_key)、UNIQUE(id,supervisor_run_id,plan_id,plan_revision,project_id)；索引(project_id,supervisor_run_id,status)，非终态(updated_at,id) |
| director_business_flow_steps | instance_id/supervisor_run_id/plan_id UUID N；plan_revision Integer N>0；step_key String120 N；scope_type String24 N；scope_entity_id UUID N；required Boolean N default true；input_refs/completion_spec JSONB object N；dependencies/result_refs JSONB array N，result_refs default []；status default pending | UNIQUE(instance_id,step_key)、UNIQUE(id,instance_id,supervisor_run_id,plan_id,plan_revision,project_id,scope_type,scope_entity_id)；索引(instance_id,status,step_key) |
| director_business_flow_step_attempts | step_id/instance_id/supervisor_run_id/plan_id UUID N；plan_revision Integer N>0；scope_type String24 N；scope_entity_id UUID N；attempt_no Integer N>0；control_epoch Integer N>=0；input_hash/payload_hash CHAR64 N；input_snapshot JSONB object N；action_kind String32 N；action_key String120 N；command_key String200 N；authorization_ref/node_run_id UUID?；receipt_ref JSONB object?；result_refs JSONB array N default []；unresolved_external Boolean N default false；error_code String80?；status default pending | UNIQUE(step_id,attempt_no)、UNIQUE(project_id,command_key)、UNIQUE(id,supervisor_run_id,plan_revision,project_id,scope_type,scope_entity_id)；索引(project_id,status,updated_at,id)；活动唯一槽见下 |

Instance七态pending/running/waiting/paused/succeeded/failed/cancelled；
Step十一态pending/ready/running/waiting_user/waiting_execution/blocked/succeeded/failed/skipped/cancelled/superseded；
Attempt八态pending/running/waiting_user/waiting_execution/unknown_submission/succeeded/failed/cancelled。
scope_type注册集合当前project/scene/shot；机构分集/研究对象仍可用project范围+typed输入引用，
Director/BusinessFlow当前目标不新增scope_type，分集/研究/资产通过project范围及typed引用表达；
ProductionGraph的asset执行目标另见D8专节，不混用两个不同作用域枚举。
action_kind=read/proposal/apply/production/repair/review，effect_class由代码合同推导，不信请求降低分类。
文本推理归Turn Invocation，不藏在read动作。

精确FK（交叉引用延迟NO ACTION）：
- Instance(supervisor_run_id,project_id)→Run(id,project_id)；
  (plan_id,plan_revision,supervisor_run_id,project_id)→Plan(id,revision,master_run_id,project_id)；
  (created_by_turn_id,supervisor_run_id,plan_revision,project_id)→Turn(id,master_run_id,plan_revision,project_id)。
- Step(instance_id,supervisor_run_id,plan_id,plan_revision,project_id)→Instance同列候选键。
- Attempt(step_id,instance_id,supervisor_run_id,plan_id,plan_revision,project_id,scope_type,scope_entity_id)
  →Step同列候选键；(node_run_id,project_id)→NodeRun(id,project_id)；
  (authorization_ref,project_id)→production_command_authorizations(id,project_id)，先补父候选键。
- Turn(business_flow_step_attempt_id,master_run_id,plan_revision,project_id,scope_type,scope_entity_id)
  →Attempt(id,supervisor_run_id,plan_revision,project_id,scope_type,scope_entity_id)；
  attempt引用非空时Run/计划必须非空。
父子/来源删除默认RESTRICT，不提供普通硬删；多态scope存在性/包含关系由领域服务核验，JSON引用不是FK。

部分UNIQUE(step_id)条件：status IN(pending,running,waiting_user,waiting_execution,unknown_submission)
OR unresolved_external。unknown_submission必有unresolved_external=true；本地取消但远端未决仍占槽，
不能由cancel释放资格而自动新Create。终态只允许补原回执/解除经核实的未决标记，不复活。
production attempt一个命令一个NodeRun，回执直接投影现有ExecutionReceipt五字段：
node_run_id、graph_id、graph_version_id、status、plan_fingerprint；不添加集合回执/第二生产状态。
node_run_id只允许NULL→核对原命令得到的唯一值，之后不可改。authorization_ref在production创建时非空，
使用现有批准command_key；缺批准保持Step等待，不先建缺授权attempt。

新计划flow_dispositions必须覆盖全部旧非终态实例（含此前retain），冻结instance revision/hash及
retain/supersede/cancel选择。retain不改原Plan身份，后续资格来自当前计划精确保留清单；
输入/定义/完成条件改变不能retain；新attempt重验当前epoch与授权。supersede/cancel保留成功事实，
取消未完成步骤并持久记录取消意图，旧未知提交仍占槽。新计划Apply不自动发起新生产。
锁顺序/合法状态边/完成注册见DIRECTOR_RUNTIME，HTTP及回执见API；字段不复制生产事实。

### 项目外发策略与目的地（R29/R32）

承接第三轮三表，现有current不全局改默认；新自主/严格路径必须有真实目的地与准入。
不存在head时GET只读等价current；首次发送准入或PUT才初始化，不能GET写库。
UUID/时间/hash/权限规则同前；表名表达策略/声明，不恢复已退役ProductPolicy三表。

| 表 | 字段及键 |
|---|---|
| provider_destination_revisions | id UUID PK；workspace_id UUID N FK workspace RESTRICT；binding_ref String200 N；revision Integer N>0；upstream_origin Text N；processing_location String16 N CHECK local/external/unknown；purposes JSONB array N；declaration_hash CHAR64 N；created_by UUID N→users；created_at N now()；UNIQUE(workspace_id,binding_ref,revision)、UNIQUE(id,workspace_id) |
| project_egress_policy_revisions | id UUID PK；project_id UUID N FK project RESTRICT；revision Integer N>0；origin_expected_revision Integer N>=0；mode String16 N CHECK current/local_only/allowlisted；policy_data JSONB object N；policy_hash CHAR64 N；created_by UUID N→users；created_at N now()；UNIQUE(project_id,revision)、UNIQUE(project_id,origin_expected_revision)、UNIQUE(id,project_id) |
| project_egress_policy_heads | project_id UUID PK FK project RESTRICT；current_revision_id UUID N；revision Integer N>0；复合FK(current_revision_id,project_id)→revisions(id,project_id)延迟NO ACTION |

policy_data={allowed_destination_revision_ids:[UUID],allowed_purposes:[typed purpose]}；
目的地数组的存在性/同Workspace由服务事务校验，不假称JSON FK。目的地来自可信管理登记，
绑定精确连接/模型修订，不接受任意URL当可信目的地。旧声明不可覆盖，声明本地仍需部署网络证据。
索引revisions(project_id,revision)、destination(workspace_id,binding_ref,revision)；两个revision仅SELECT/INSERT，
head SELECT/INSERT/UPDATE，均FORCE对应项目/Workspace RLS、撤DELETE/TRUNCATE。

Project锁下先判PUT expected_revision=0：无head则直接创建所要求revision1，不先创建current再拒绝自己。
准入先初始化则后到的expected0更新冲突；重放按origin_expected_revision+policy_hash返回原修订，
异hash409。head/新revision/PolicyChanged同事务。

实际发送证据绑定原调用：
- Invocation.request_snapshot.egress_admission（文本/研究文本）；
- ProviderOperation.request_summary.egress_admission（媒体及统一链TTS）；
- ArtifactReferenceToken增加egress_admission JSONB?，对新增准入路径必填；
  公共引用还需消费项目和发布链接，不能使用源项目策略冒充消费许可。
admission固定schema_version/policy_revision_id/destination_revision_id/purpose/payload_hash/
operation_id/admitted_at/decision=allowed/authorization_ref?；服务及字段冻结保护，不新增通用外发任务表。
D7补required_purposes非空去重枚举数组，必须含主purpose且由实际载荷分类推导；
研究/对话带Vision时要求两种用途全部获准。它与purpose分别表达主业务目的和完整准入条件，不能由客户端写入。
旧Invocation/Operation不补造准入证据，不重发。外部存储若无可绑定原操作与许可的路径则拒绝该新出口，
不临时建第二操作记录。D5审查OCR/Vision/ASR等所有实际发送入口及独立知识操作的作用域，未覆盖不启用。


### 来源使用限制与生成血缘（R07/R18/R29/R32，D2目标）

当前源码没有完整来源许可与撤销传播模型。Artifact.produced_by_run_id只证明生产来源，
不能表达文化资料/知识/公共素材的使用限制；不覆盖或改挂该字段。
以下是业务使用限制，和项目外发策略是两道检查，任一道拒绝都不能新发送。
用户声明可用不等于系统给出版权合法性结论，界面保留声明来源和待核实状态。

| 表 | 字段与默认 | 键/约束/权限 |
|---|---|---|
| source_use_subjects | id UUID PK；project_id UUID N；file_revision_id UUID?；artifact_id UUID?；current_revision_id UUID?；version Integer N default1；created_at N now() | 两source列恰一非空；UNIQUE(id,project_id)、部分UNIQUE(file_revision_id)、部分UNIQUE(artifact_id)；project RESTRICT；文件/Artifact复合FK绑定原project；项目FORCE RLS |
| source_use_revisions | 公共列；subject_id/project_id UUID N；number Integer N>0；origin_expected_version Integer N>0；result_version Integer N>1；state String16 N；allowed_uses JSONB array N；statement Text N；evidence_note Text N default ''；content_hash CHAR64 N；request_key String160 N；request_hash CHAR64 N | state unreviewed/declared/revoked；result_version=origin_expected_version+1；UNIQUE(subject_id,number)、UNIQUE(subject_id,origin_expected_version)、UNIQUE(project_id,request_key)、UNIQUE(id,subject_id,project_id)；FK(subject_id,project_id)→subjects；不可变、项目FORCE RLS |
| artifact_source_uses | id UUID PK；project_id/artifact_id UUID N；source_subject_id/source_project_id/source_revision_id UUID N；consumer_node_run_id UUID N；input_role String40 N；created_at N now() | FK(artifact_id,project_id)→Artifact；FK(consumer_node_run_id,project_id)→NodeRun；FK(source_revision_id,source_subject_id,source_project_id)→source_use_revisions(id,subject_id,project_id)；UNIQUE(artifact_id,source_subject_id,input_role)；不可变、目标project RLS |

source_use_subjects.current复合FK(current_revision_id,id,project_id)→source_use_revisions(id,subject_id,project_id)
延迟NO ACTION。新subject可短暂NULL，读作unreviewed，不能自动宣称许可已证明。文件复合FK用
project_file_revisions(id,project_id)新增候选键；Artifact/NodeRun同样补精确候选键。
allowed_uses只允许research/creation/library_reference/external_processing/export，state=revoked时数组为空；
declared必须有非空statement和至少一个用途。内容范围及用途集合由typed服务校验，不接受自由策略表达式。

SourceSubject当前指针/版本是唯一现行使用限制；revision保留每次声明/撤销，Project egress仍只管外发。
更改锁Subject，先回request_key+hash再CAS，追加revision+指针+Outbox同事务。
public_asset_publications.status=restricted仅为界面投影，不替代实时SourceSubject检查；投影迟到不能放行。
来源限制查询不得向另项目返回statement/evidence_note或原始资料，只给allowed/reason/不透明资格版本。

ArtifactSourceUse由生产成功落Artifact的同一事务建立，输入来自已冻结且服务端核验的NodeRun输入依据，
不能由模型自报删除限制。引用私有资料时记录该原件subject；引用研究时展开实际消费citation对应的原件subject；
引用公共生成素材时记录来源Artifact subject并保留其递归依赖；引用知识时保留固定知识revision及其有效用途，
再通过受限SourceLink核验原件限制。需要把知识/公共链接的输入引用写入现有input_snapshot，
不能用新增血缘表替代冻结生产输入。

actor只能在当前合法资料/公共引用授权下建立跨项目输入边，不因可写目标project就能声称任意源许可。
跨项目最小资格检查沿公共引用窄端口，私有引用不得跨项目；跨Workspace仅允许同owner（N05），源与消费Workspace分别从DB确认，不信客户端owner。
SourceSubject与输出Artifact不重复保存原件正文/媒体，不新造Artifact或NodeRun。
依赖图必须无环；新输出边只引用生成输入时已存在的源，禁止输出Artifact自引用或后补改为其后代。
迁移/服务在写入时校验环及同NodeRun血缘；硬删源或边均RESTRICT，不能借归档清除限制。

撤销先持久SourceRevision并提高version；新发布、新引用、新生产、令牌签发和下载在受理时复核依赖闭包。
已被发送的数据不能追回，恢复仍只查询原操作；已有作品保留并标复核，不自动销毁、替换或重生成。
冻结准入包含全部实际消费的source revision版本；新发送时任一版本变化则预览失效。
索引subjects(project_id,id)、revisions(subject_id,number)、uses(source_subject_id,artifact_id)和
uses(project_id,artifact_id)支持撤销影响查询。依赖闭包超限/不完整返回需核验，不省略深层限制放行。

历史Artifact缺来源不补造“许可已确认”。首次进入公共库仍登记采用事实，但资格为restricted，
用户补足明确依据后才可新引用；普通旧current生产的渐进策略由O4/D5明确，不擅自全局改变现有外发默认。
本节权限使用subject/read scope、不是新通用网络日志或审批平台。

### 分集剪辑与可核验交付（R13/R27/R33–R35）

实际EditSession只有project_id，没有episode_id；Export已有nullable episode_id但为SET NULL，
FinalFilm dirty实现从NodeRun.input_snapshot冻结edit_session_id/timeline_version/request_fingerprint，
目前不能据此宣称逐集生产和成片验收已经具备。以下只规定目标，不覆盖该未提交实现。

EditSession新增episode_id UUID?；NULL为项目级剪辑，非空须FK(episode_id,project_id)→episodes(id,project_id)，
新增Episode候选键；ON DELETE RESTRICT。UNIQUE(edit_sessions.id,project_id)，索引(project_id,episode_id,id)。
另增scope_confirmed_at timestamptz?，旧行NULL，新建/显式确认范围由服务赋值；新导出要求非空，
不能仅凭旧episode_id=NULL猜测用户已选择多集汇编。scope变更与timeline同一次version CAS。
creation_request_key String160?/creation_request_hash CHAR64?同空同非空，部分UNIQUE(project_id,creation_request_key)，
新建会话要求键，旧行不补造。创建回执只含session_id/created_version=1，不用后来timeline冒充原创建响应。
已保存timeline中的Shot必须通过Scene→Episode属于该指定集；D8 schema2资产Clip按消费会话归集，
其来源保持固定已采用AssetVersion/公共Link，不造假Shot。项目级会话允许显式多集汇编。
旧EditSession保持NULL，不从名称或镜头数量猜分集。切换集作用域需版本化Save并明确检查全部Clip，不静默删Clip。

Export保留既有事实，episode FK改精确复合RESTRICT，增加
edit_session_id UUID?、timeline_version Integer?、timeline_hash CHAR64?、render_node_run_id UUID?。
四列全空表示旧非成片导出，或全非空表示新成片回执；版本>0，hash小写hex64。
FK(edit_session_id,project_id)→EditSession(id,project_id)；
FK(render_node_run_id,project_id)→NodeRun(id,project_id)，不把可变会话当前version当FK目标。
新增成片format的写入口要求四列全非空；旧真实manifest可证明时仅复制既存绑定，不造历史回执。
索引(project_id,episode_id,created_at,id)、(edit_session_id,timeline_version)及(render_node_run_id)。

不可变timeline快照仍在该render NodeRun.input_snapshot，Export列是绑定索引，不新建第二份可变timeline事实；
manifest版本/hash必须与列及该run快照一致，服务校验并由约束触发器守住绑定不可改。
ExportItem固定MP4/SRT来源Artifact；成片完成条件核对Export、items、Artifact状态/类型、同项目和
原render NodeRun结果。下载链接/按钮出现不等于字节已验证；I9/I10执行ffprobe/字幕/实际下载检查。
源Episode不能因删除变NULL冒充项目级导出；归档保留既有交付。

### 目标完成条件的数据表达（R20/R33–R35）

保留P1 shot_formal_artifact_v1精确已知Artifact核验，但它不是完整机构目标唯一predicate。
Plan.completion为注册的typed声明，至少一项且all_required=true，不接受任意脚本、SQL或客户端结果。
D3注册以下可表达未来输出的合同，声明是目标，完成时读取真实正式事实：

| predicate | 冻结输入 | 服务端事实核对 |
|---|---|---|
| shot_formal_artifact_v1 | shot_id、stage、artifact_id、expected_shot_version | 精确版本与Formal指针、可用Artifact及合法血缘；不自动Formal |
| asset_version_adopted_v1 | asset_id/asset_version_id或注册采用输出槽、require_current、required_reference_roles、require_publication、required_use可选 | 同项目已采用不可变版本、实际Reference/Artifact可用；要求current则当前指针一致；要求发布则记录未withdrawn，要求用途则实时资格通过；生成候选不能满足 |
| research_ready_v1 | 明确file_revision_ids、要求的六类kind集合、最低coverage、是否允许unverified | 全部源修订解析覆盖与当前研究结果/引用有效、没有未处理文件；不以一条摘要代替全量 |
| source_extraction_ready_v1 | file_revision_id、accepted_attempt、processor_profile_revision、要求处理范围/coverage | 当前可用源修订/attempt的成功Extraction及完整所需块/hash，未知/旧attempt/incomplete不算完成；不要求调用LLM |
| business_flow_completed_v1 | 当前计划flow_key、definition key/version/hash | 合法当前/retain实例全部required步骤的注册完成规则满足；不是仅看一列succeeded |
| episode_export_ready_v1 | episode_id或注册Flow输出槽、所需MP4/SRT、输入版本要求 | 解析槽必须来自本Run当前计划的正式Apply/交付回执；同项目/指定集、保存timeline、完整ExportItem及可用媒体 |
| project_delivery_ready_v1 | work_type、所需集列表或当前计划分集Apply输出槽、交付规格 | type匹配；全部指定集出口成立；宣传片可项目级输出；多集必须逐集检查，不用单集成功代替 |

输出槽只允许注册step_key+typed output field，不接受任意JSONPath；创建后由已有正式命令回执解析ID，
验证来源项目、计划、定义和版本。用户未Apply的提案、模型自报ID或临时候选不能满足槽。
目标不能通过换新计划偷偷减少已承诺集数：新范围需用户明确计划确认并记录变更原因。
验证结果保存在原控制回执/事件中，可重算；不新建独立“目标产物”或通用完成事实表。
本表是D2结构与实体落点；锁序、每个predicate的精确类型/错误与并发原子核验在D3/D7细化。


### 研究覆盖清单与零发现（R05/R06/R09）

交叉检查发现：仅凭ResearchResult数量不能证明“六类分析完成”。资料可能没有人物、日期或事件，
不能为了满足predicate伪造条目。补充不可变研究覆盖清单，表示一次已取得结果的分析，而非第二任务状态机。
排队/运行/失败/重试仍归Turn/BusinessFlow/Invocation；以下记录不保存lease、队列状态或重试控制。

| 表 | 字段 | 约束/索引 |
|---|---|---|
| research_analyses | 公共列；project_id/file_revision_id/source_extraction_id UUID N；coverage JSONB object N；category_outcomes JSONB object N；manifest_hash CHAR64 N；request_key String160 N；request_hash CHAR64 N；completed_at timestamptz N | UNIQUE(project_id,request_key)、UNIQUE(id,file_revision_id,project_id)；FK(source_extraction_id,file_revision_id,project_id)→source_extractions(id,file_revision_id,project_id)；不可变、项目FORCE RLS；索引(project_id,file_revision_id,completed_at,id) |
| research_analysis_invocations | analysis_id/project_id/invocation_id UUID N；ordinal Integer N>=0 | PK(analysis_id,invocation_id)、UNIQUE(analysis_id,ordinal)；FK(analysis_id,project_id)→research_analyses(id,project_id)，新增父候选键；FK(invocation_id,project_id)→director_invocations(id,project_id)；不可变、项目RLS |
| research_analysis_results | analysis_id/project_id/research_revision_id UUID N；category String24 N；ordinal Integer N>=0 | PK(analysis_id,research_revision_id)、UNIQUE(analysis_id,category,ordinal)；FK(analysis_id,project_id)→analyses；FK(research_revision_id,project_id)→research_result_revisions(id,project_id)；category六值；不可变、项目RLS |

ProjectFileRevision新增current_analysis_id UUID?，
FK(current_analysis_id,id,project_id)→research_analyses(id,file_revision_id,project_id)延迟NO ACTION。
完成时在Project/FileRevision锁内重验原件修订、current_extraction_id、处理attempt和任务资格，
追加Analysis/links、首次结果或AI候选以及当前分析指针，Outbox同事务。
分析响应丢失按request_key/hash回原清单；同键异载荷拒绝，不再调用模型。
新分析清单指针不意味着覆盖用户的ResearchResult.current_revision_id，两者分别表示分析覆盖与有效研究内容。

category_outcomes必须恰含summary/person/place/event/timeline/cultural_clue，每项
{outcome: findings|none|incomplete, source_fragment_ids:[UUID], output_count:int>=0, reason_code?}。
findings要求count>0且实际analysis_results该类别数量一致；none要求count=0但有已检查范围，
不是缺字段或调用失败；incomplete必须说明未处理/缺证原因，不能报“全部分析完成”。
coverage记录输入总范围、实际处理范围及明确遗漏，schema版本与hash冻结在manifest。
source_fragment_ids必须属于同一Extraction；服务检查整个清单和每条Citation，不把JSON当外键保证。

research_ready_v1核对有效Analysis及实际输出集合/覆盖、零发现和当前用户修订，不要求每类至少一条事实。
若用户主动归档/纠正条目，保留Analysis当时的输出证据但按最新有效研究回答，不能复用旧分析覆盖来覆盖用户决定。
独立知识录入不需要此清单；手工研究也不伪造模型分析完成证据。


### 目标ER与表清单（D2审查视图）

以下图覆盖新增数据域及其已有父事实；列/FK精确顺序以上文为准。Knowledge/PublicAsset按N05采用同用户共享，
Workspace分别表示创建/源与消费空间，不阻止同owner跨空间。
未改变的Access/Production/Review/Editing/Provider表继续使用本文Model ownership及实际ORM，
不另抄一份可漂移的现有Schema。

~~~mermaid
erDiagram
  Project ||--o{ ProjectFile : owns
  ProjectFile ||--o{ ProjectFileRevision : versions
  ProjectFileRevision ||--o{ SourceExtraction : parsed_as
  SourceExtraction ||--o{ SourceFragment : contains
  SourceExtraction ||--o{ ResearchAnalysis : analyzed_as
  ResearchAnalysis ||--o{ ResearchAnalysisInvocation : evidence
  DirectorInvocation ||--o{ ResearchAnalysisInvocation : supplies
  ResearchAnalysis ||--o{ ResearchAnalysisResult : outputs
  ResearchResultRevision ||--o{ ResearchAnalysisResult : records
  Project ||--o{ ResearchResult : owns
  ResearchResult ||--o{ ResearchResultRevision : versions
  ResearchResultRevision ||--o{ ResearchCitation : cites
  SourceFragment ||--o{ ResearchCitation : locates
  User ||--o{ KnowledgeEntry : owns
  KnowledgeEntry ||--o{ KnowledgeRevision : versions
  KnowledgeRevision ||--o{ KnowledgeSourceLink : traces
  ResearchResultRevision ||--o{ KnowledgeSourceLink : private_source
  KnowledgeRevision ||--o{ ProjectKnowledgeReference : pinned
  Project ||--o{ ProjectKnowledgeReference : consumes
~~~

~~~mermaid
erDiagram
  Project ||--o{ Asset : owns
  Asset ||--o{ AssetVersion : versions
  AssetVersion ||--o{ AssetVersionReference : references
  Artifact ||--o{ AssetVersionReference : original_media
  AssetVersion ||--o| PublicAssetPublication : adopted
  PublicAssetPublication ||--o{ PublicAssetPublicationItem : exposes
  AssetVersionReference ||--o{ PublicAssetPublicationItem : pinned
  PublicAssetPublication ||--o{ ProjectPublicAssetLink : reused
  Project ||--o{ ProjectPublicAssetLink : consumes
  ProjectPublicAssetLink o|--o{ ShotReferenceBinding : authorizes
  ProjectFileRevision o|--o| SourceUseSubject : restriction_subject
  Artifact o|--o| SourceUseSubject : restriction_subject
  SourceUseSubject ||--o{ SourceUseRevision : declarations
  SourceUseRevision ||--o{ ArtifactSourceUse : frozen_at_creation
  Artifact ||--o{ ArtifactSourceUse : depends_on
  NodeRun ||--o{ ArtifactSourceUse : production_evidence
~~~

~~~mermaid
erDiagram
  Project ||--o{ MasterRun : owns
  DirectorThread ||--o{ MasterRun : conversation
  DirectorTurn ||--o| MasterRun : origin
  MasterRun o|--o{ DirectorTurn : supervises
  MasterRun ||--o{ MasterRunPlanRevision : plans
  DirectorProposalItem ||--o| MasterRunPlanRevision : user_gate
  MasterRun ||--o{ MasterRunControlReceipt : decisions
  MasterRunPlanRevision ||--o{ BusinessFlowInstance : creates
  BusinessFlowInstance ||--o{ BusinessFlowStep : contains
  BusinessFlowStep ||--o{ BusinessFlowStepAttempt : attempts
  BusinessFlowStepAttempt o|--o{ DirectorTurn : continues
  NodeRun o|--o{ BusinessFlowStepAttempt : original_receipt_reference
  ProductionCommandAuthorization o|--o{ BusinessFlowStepAttempt : exact_command
  Project ||--o{ EgressPolicyRevision : policy_history
  Project ||--o| EgressPolicyHead : current_policy
  Workspace ||--o{ ProviderDestinationRevision : declaration
  Episode o|--o{ EditSession : optional_scope
  EditSession o|--o{ Export : delivery
  NodeRun o|--o{ Export : original_render
~~~

新增表27张：

既有表目标扩展的关系补充（JSON选用证明/快照不冒充外键）：

~~~mermaid
erDiagram
  Workspace ||--o{ ProductionModelProfile : owns
  Project o|--o| ProductionModelProfile : project_defaults
  ProviderModelBinding o|--o{ ProductionModelProfile : image_default
  ProviderModelBinding o|--o{ ProductionModelProfile : video_default
  ProviderModelBinding o|--o{ ProductionModelProfile : voice_default
  Project ||--o{ ProductionCommandAuthorization : owns
  Shot o|--o{ ProductionCommandAuthorization : shot_target
  Asset o|--o{ ProductionCommandAuthorization : asset_target
  Asset ||--o| ProductionGraph : asset_scope_trigger
  NodeRun o|--o{ ProductionCommandAuthorization : accepted_receipt
  NodeRun o|--o| ProviderOperation : one_original_operation
  DirectorTurn ||--o| DirectorRuntimeControl : execution_control
  DirectorRuntimeControl ||--o{ DirectorRuntimeSignalClaim : signal_receipts
~~~

上图asset_scope由显式触发器/服务验证，不虚称通用scope_entity_id是原生FK；授权shot/asset互斥。
“新增表27张”统计不因给已有表增加列/关系而增加，以下为确切新增清单：
- 解析2：source_extractions、source_fragments。
- 研究6：research_results、research_result_revisions、research_citations、research_analyses、
  research_analysis_invocations、research_analysis_results。
- 知识4：knowledge_entries、knowledge_revisions、knowledge_source_links、project_knowledge_references。
- 公共资产3：public_asset_publications、public_asset_publication_items、project_public_asset_links。
- 来源限制3：source_use_subjects、source_use_revisions、artifact_source_uses。
- 目标3：director_master_runs、director_master_run_plans、director_master_run_control_receipts。
- 业务流程3：director_business_flow_instances、director_business_flow_steps、director_business_flow_step_attempts。
- 外发3：provider_destination_revisions、project_egress_policy_revisions、project_egress_policy_heads。

NodeRun与Attempt图示表达引用：一个attempt至多关联一个NodeRun；当前目标没有声明node_run_id在全部attempt间全局唯一。
不能从“多次引用原回执”推导多次Create，实际受理由grant/command_key/原NodeRun唯一事实约束。

这些是不同领域事实，不按表数量追求“完成”。D8若合并或删除表必须证明其业务事实仍被单一现有持久对象完整表达，
不能为少表把私有研究、公开快照、执行状态与生产事实揉进一个无约束JSON列。

### 既有表扩展与删除边界汇总

| 既有表 | 目标变化 | 保留/删除边界 |
|---|---|---|
| projects | work_type/creative_goal/audience/时长/集数意图；id/workspace候选键 | 旧项目不猜类型；不修改金额字段语义 |
| project_file_revisions | extraction/analysis当前指针及源复合候选键 | 原件列不改义；excerpts消费者全部切换后移除旧提取正文写入口 |
| director_threads/proposal_items/invocations | 精确scope候选键用于新引用 | 不新造Thread/Approval/LLM日志 |
| director_turns | master_run/plan/attempt关联及精确候选键 | 旧八态/请求身份/Turn引擎/租约按O6保留至回归评估 |
| assets/asset_versions/asset_version_references | 源身份候选键、ref精确FK；version.base_publication_id | 原版本与reference不复制；已发布内容不可变，生命周期状态按原语义 |
| shots/episodes/scenes | 分集/项目归属候选键及受影响FK | 不恢复Character旧表，不改Formal所有者 |
| shot_reference_bindings | public link/publication组合引用 | 旧私有路径保持，新增公共路径必须精确资格 |
| artifacts/node_runs/production_command_authorizations | (id,project_id)候选键 | 不改变produced_by_run_id/原授权事实；不重造执行 |
| artifact_reference_tokens | 消费项目/公共item/link、egress_admission及组合键 | 源Artifact身份保留；下载校验撤销；不记录明文token |
| edit_sessions | episode_id、scope候选键/索引 | timeline仍由会话版本拥有，渲染快照在原NodeRun |
| exports | 精确episode FK及成片绑定列 | 旧非成片记录不伪造绑定，新成片必须完整 |

旧Workflow只是分类改名，不据此新增Workflow表；删除旧Turn lease不是D2自动决定。
删除原excerpts列只能在消费者全部改为不可变SourceExtraction、已有内容有无损映射、相关回归通过的切片执行。
真正数据删除/不可逆迁移按主合同人工门，不把“未发布产品”理解为可丢弃当前资料。

### 角色与不可变保护清单

| 集合 | 运行角色操作 | 强制检查 |
|---|---|---|
| Extraction/Fragment、所有研究revision/citation/analysis/links、KnowledgeRevision/SourceLink、PublicationItem、SourceUseRevision/ArtifactSourceUse、Plan/ControlReceipt、Egress/DestinationRevision | SELECT/INSERT；撤UPDATE/DELETE/TRUNCATE | FORCE相应作用域RLS；冻结内容只追加；禁止继承角色恢复写权 |
| ResearchResult、KnowledgeEntry、PublicPublication、ProjectKnowledgeReference/PublicAssetLink、SourceUseSubject、MasterRun、PolicyHead | SELECT/INSERT/UPDATE，有限字段白名单；无普通DELETE | current指针归属、CAS、同事务revision/事件；仅领域writer能改状态 |
| Flow三表 | SELECT/INSERT/UPDATE；冻结列触发器 | 唯一活动attempt、一次回执绑定、终态不复活、scope复合FK |
| 私有源跨域读取 | 不开放普通跨project SELECT | 窄资格端口，仅返回已批准公共内容/允许与否；不得输出原私有研究或原件地址 |
| Checkpoint私有schema | 既有checkpoint专用角色 | 不加入应用model_registry，不混入业务迁移角色或公共知识授权 |

需要新模块时先由model_registry显式导入其ORM，Alembic metadata覆盖新图，不能“有迁移无应用模型”。
所有GRANT后再执行精确REVOKE，并在真实运行login/成员关系下验证；owner和超级用户不作为RLS通过样本。
本节没有启动数据库；上述是待实施与待测试合同。

### 迁移依赖与回退设计

先核验当前唯一head、实例catalog/roles/在途任务与完整受保护数据，再在隔离库验证。只追加新revision，
不改103份历史迁移。版本号按实施时真实head分配，本设计不预先创建空迁移占号。

1. 增加已有表候选键，先查重/查跨项目错配；有异常阻断，输出ID及数量的安全摘要，不自动删/合并。
2. 新解析/研究/来源限制表先建根和不可变修订，再加循环current FK；导入既有excerpts只保留实际能证明的内容。
3. 目标/Plan/Receipt按Run暂不current→Plan→Turn关联→循环FK，随后Flow三表/attempt与Turn互引。
4. 知识/公共发布及项目链接依赖源身份和限制；按N05同owner跨Workspace冻结组合键及RLS。
5. 外发目的地→策略revision/head→原调用证据/令牌扩展；旧操作不补造已发送准入。
6. 分集会话/Export绑定，旧记录保持真实NULL；全新写入口必须新合同；统一应用注册器、权限、索引和扫描入口。
7. 完整upgrade/check/RLS/并发/历史行与hash对比通过后才考虑切换写入；旧lease排空与删除另按O6。

空新表可按反向依赖验证downgrade；存在来源/研究/公开引用/目标/回执时拒绝破坏性downgrade。
代码回退先停止新接纳，保留读取/已有操作恢复与所有数据，不能把strict策略退成current。
需要不可逆列删改或真实库恢复时给出备份验证、影响对象与动作，按主合同审批；隔离数据库实验允许自主。
当前实例停止且未核验，不能给出“已可无损升级”的运行结论。

### D2数据验收设计（尚未执行）

| Case | 必须观察的结果 |
|---|---|
| DB01 来源定位 | 同修订不同解析attempt分别保留；旧引用可回溯；新attempt的迟到结果不能改当前指针 |
| DB02 研究写入 | user/restore/accept并发仅一个CAS成功，失败保留输入；同请求回放原applied版本，当前后来变化也不伪装原回执 |
| DB03 覆盖零发现 | 人物/时间线无发现合法，未处理/incomplete不能冒称六类成功；不能生成占位人物来通过 |
| DB04 私有与公开 | 跨项目/Workspace访问按最终边界拒绝或仅回安全快照；猜私有源ID、下载原件、读取SourceLink均拒绝 |
| DB05 撤销与发送 | 先撤销则零新发送；先准入则记录在途并继续原身份核对；下载复核，未知提交不重发 |
| DB06 公共引用 | 固定版本、真实变体、不复制Artifact/NodeRun；项目归档不破坏他项目已授权引用，硬删除被依赖限制 |
| DB07 目标身份 | workflow/threadless/跨actor/项目的origin拒绝；Plan/Turn/Flow跨父关系直接SQL也拒绝 |
| DB08 控制与流程 | 同键回执一份；活动attempt唯一且cancelled+unresolved占槽；retain不改旧实例创建计划，终态不复活 |
| DB09 分集导出 | 另一集Clip混入拒绝；导出绑定原timeline/run/MP4/SRT；删除集不能把交付变成项目级 |
| DB10 迁移与权限 | 空库/当前head升级一致；历史ID/原件hash/原调用/正式指针不变；真实受限角色的越权与不可变UPDATE拒绝 |
| DB11 回退 | 空表逆依赖成功、有数据破坏性降级拒绝；代码回退不降安全策略、不重放外部操作 |
| DB12 完成核验 | 一集/一个Flow完成不能代整剧；typed输出槽只能来自当前合法计划的正式事实，无客户端成功字段 |

D7再把case映射实际测试文件/命令，D2不以文字case冒称PG测试通过。


### 研究/来源JSON的类型边界（D2存储合同）

所有JSON写入拒绝未知字段和超配置上限，不让任意JSON承担执行拓扑或授权。
以下定义存储形状，解析算法/分块/质量在D4，HTTP响应模型在D7；不能因API未冻结而在数据库写无版本对象。
正文与定位hash采用schema_version+完整规范化payload（含引用身份），禁止NaN、无效Unicode和未经解释的时间值。

SourceFragment.locator判别联合（所有序号从0开始，区间end不包含；页码page_index从0开始）：
- paragraph：{kind,paragraph_start:int>=0,paragraph_end:int>start,char_start:int>=0,char_end:int>=start}；
- page_region：{kind,page_index:int>=0,bbox:[x0,y0,x1,y1]}，坐标归一化0..1且x0<x1/y0<y1；
- image_region：{kind,bbox:[x0,y0,x1,y1]}，同归一化规则；
- time_range：{kind,start_ms:int>=0,end_ms:int>start,track:string,frame_time_ms?:int}，
  frame时间在区间内，不以ASR文本的字符位置冒充视频位置；
- table_cells：{kind,sheet:string,row_start:int>=0,row_end:int>start,column_start:int>=0,column_end:int>start}。

DOCX段落/表格各自使用对应locator；一个Fragment不混两种坐标。PDF无区域定位时允许明确整页bbox，
不能编造精确词框。legacy旧excerpts无法可靠定位时在Extraction.coverage标location_unverified，
不能声称“引用精确页码通过”；保持原locators供人工复核，迁移遇未知种类中止转换而不丢原值。

ResearchRevision.body必含schema_version=1、claim_type=fact|interpretation|creative_suggestion，
再按ResearchResult.kind接受以下字段（对象多余键拒绝）：
- summary：{text:string,scope_note:string}；
- person：{display_name:string,aliases:[string],description:string,related_result_ids:[UUID]}；
- place：{display_name:string,aliases:[string],description:string,related_result_ids:[UUID]}；
- event：{title:string,description:string,time:{label:string,start_iso?:string,end_iso?:string,precision:unknown|year|month|day|range},
  participant_result_ids:[UUID],place_result_ids:[UUID]}；
- timeline：{items:[{item_key:UUID,title:string,time:上述time对象,event_result_id?:UUID,description:string}]}；
- cultural_clue：{title:string,interpretation:string,related_result_ids:[UUID]}。

数组UUID必须指同项目可见ResearchResult；按业务kind校验person/place/event引用类型，不能同名猜关联。
ISO时间仅在资料确能支持时填写；未知保持label+precision=unknown，不补默认当天日期。
这些业务时间不使用服务器created_at替代。版本化body被引用后不可覆盖，关系指向稳定Result身份，
该次使用到的具体revision记录在输入上下文快照中，不因此静默采用对方未来版本。

ResearchCitation增加claim_key String120 N default root，唯一改为
(research_revision_id,claim_key,source_fragment_id)。summary/person/place/event/clue使用root；
timeline使用item:<item_key小写UUID>，服务必须找到该revision中的对应item。不允许任意JSONPath执行。
locator_override若非NULL必须是原fragment范围内的同kind子范围，不能扩大到未读取原文。
quoted_text为空表示来源依据而非逐字引用；非空须可从该Fragment确定取得或标为OCR原样片段，
不能用模型改写文字冒充原文引文。引用校验失败保留待核实结果，不生成伪引用。

KnowledgeRevision.body复用同kind内容字段，但关联字段改为related_entry_ids、participant_entry_ids、
place_entry_ids、event_entry_id，仅可指当前用户可检索的已发布KnowledgeEntry；不携带私有ResearchResult UUID。
不能转成合法知识关联时保留安全文字说明并省略关联，不能将私有对象ID直接序列化出去。
safe public_source_notes只允许{label:string,public_url?:validated URL,locator_note?:string}，
不允许project id/object key/secret/签名令牌；URL只是显示来源，不授权服务器自动抓取。
SourceLink保留私有溯源映射；发布后公开正文是冻结快照，不是私有研究的一份可变镜像。

schema_version未知拒绝新写与执行，历史读显示不支持并保留数据，不自动套最新版重新解释。


### 来源依赖的跨项目资格与异步完成

artifact_source_uses增加source_access_kind String24 N CHECK private/public_asset/published_knowledge，
access_basis JSONB object N。private要求source_project_id=project_id，basis为空对象。
public_asset的basis={public_asset_link_id,publication_id,publication_item_id,source_artifact_id}；
published_knowledge的basis={project_knowledge_reference_id,knowledge_revision_id,source_link_id,citation_id}。
未知kind/多余键拒绝。所有UUID由服务读取实际引用链，不由LLM提供权限。

这组JSON不声称有FK保证，数据库约束触发器须核对下列关系和NodeRun冻结快照中的同一basis：
- public_asset：链接属于消费project；item属于该publication并指来源Artifact；
  SourceUseSubject正是该Artifact的subject；源/消费Workspace都属于publication.owner。
- published_knowledge：项目知识引用属于消费project且固定该revision；SourceLink属于此knowledge revision、
  绑定指定研究修订；Citation属于该研究修订并指SourceSubject的确切文件修订；两侧owner相同。
- private：SourceSubject属于本project，并且实际被该NodeRun输入消费，而不是任意添加的来源。

跨项目触发器通过窄验证函数返回Boolean/受控错误，不将私有SourceLink/Citation正文返回调用方，
函数固定search_path/严格输入/REVOKE PUBLIC；审计记录ID/hash，不能因为需要检查而暴露原文。
合法授权链中的源ID可以保存在受限内部血缘中，公共DTO仍不能序列化。查询血缘也按输出project权限过滤。

授权检查分两个时间点：新发送前锁定并核验当前资格，冻结input_snapshot中的来源revision与basis；
已发送任务成功落Artifact时，只核对原冻结准入及实际输出身份并写历史依赖。即使此时来源已撤销，
也不能拒收原任务结果、丢失血缘或重发任务。后续新引用/新发送再次查当前限制，撤销因此阻断未来使用。
该区别避免把合法在途完成误判成一次新的外发授权。

所有源revision/公共发布/知识revision及链接的已引用行RESTRICT保留。用户解除关联用detached状态，
不能删除行破坏原准入证明。没有可证明的basis则记录来源不完整、限制新共享；不猜源许可。
D5核验生成提示词中的研究/知识依据是否全部进入该快照，缺一类输入不得宣称来源限制完整覆盖。


### 研究提交的排他与空指针规则

一次分析发布由稳定request_key绑定原file revision、extraction、所用Invocation集合及输入版本hash。
Worker先检查同键既有Analysis：同hash返回原清单，异hash冲突；不重新分配Result ID或再调用模型。
无既有结果时锁Project→File→FileRevision，再校验current extraction、处理attempt及任务epoch，
在同一事务插入Analysis、输出Revision/Citation、关联清单和所需current指针。任何失败整批回滚，
已完成Invocation证据保留供读取恢复，不重发外部调用。

首次分析可新建结果并设当前。再分析必须把既有条目明确指定为result_id/base_revision；
不能按姓名模糊合并；无匹配的新建议创建current_revision_id=NULL的待采用Result，只出现在“新发现”列表，
不混入当前有效研究或正式上下文。用户accept后新建带applied_result_version的revision并推进current。
未采用且无current的Result不被research_ready当作有效事实，但Analysis仍保存该建议产出，允许明确零发现。
Result编号在行锁内分配；两个Analysis针对同一Result的候选可共存，current推进由CAS独占。

FileRevision.current_analysis_id只表示最近一次已发布的分析清单，不代表当前结果覆盖用户意见。
新解析完成后若旧Analysis.source_extraction_id不等于current_extraction_id，读模型显示待再分析；
不能用旧清单满足当前解析覆盖predicate。新文件修订也不能借旧Revision的分析清单宣称完成。
资料解除关联后新分析不推进current；已在途返回可留调用证据但不能恢复关联或替换用户研究。

Result/Entry的current=NULL仅允许初始化或待采用对象。普通研究/知识检索排除无current对象，
建议列表需显式请求；知识published时current不得NULL，由约束触发器强制且指向本Entry的publish修订。
SourceSubject.current=NULL解释为unreviewed；无策略head解释为O4的current继承，两者不是同一安全含义。

### D2审查结论与后续合同

数据设计审查通过，尚未实施。审查覆盖新增表及既有扩展的字段/类型/NULL/默认、候选键、FK、
索引、RLS、不可变与删除边界、JSON核心形状、ER、迁移顺序/回退及DB01–12负向设计。
27张表定义存在性与3幅ER围栏已静态核对；这仅佐证交付完整性，不作为数据库行为测试。

关系审查逐链核对：原件→Extraction→Analysis/Fragment→ResearchRevision/Citation；
Knowledge/SourceLink/ProjectReference同owner跨空间且私有来源不公开；Publication/Item/Link/Variant/Token
在源项目、消费项目、owner间完整绑定；Run/Plan/Turn/Flow/Attempt回到唯一NodeRun；Egress准入回到原调用；
EditSession/Export回到确定Episode及原render快照。复合外键的nullable例外有同空/同非空或状态前置检查，
JSON引用明确由typed服务/约束触发器核验，不伪称数据库天然FK。

审查修复：六类零发现不能伪造条目；研究采纳/恢复必须不可变回执；当前指针变更匹配新受理版本；
同用户跨Workspace共享不能被旧同workspace键缩小；新发送与在途结果落库的资格检查时间不同；
归档不CASCADE删除公共引用；旧成片记录不补造不存在的timeline绑定。

D3继续精确锁序、状态边、predicate及Runtime控制；D4补解析/研究算法与上下文；D5补所有实际出口
和撤销竞态；D7确定DDL/调用错误与自动化文件，D8交叉审计所有回填。它们是后续执行合同，
不是另一个数据事实源。后续发现字段/约束不足必须返回本节修订及复查，不能直接偏离实施。
运行Schema、真实角色、PG约束/并发及迁移验证仍未证明；I0/各实施门必须取得实际证据，不降低最终验收。

### D3回填：控制位置与监督槽（未实施）

旧Agent源码实际已经设置engine_version、director-agent-v1、runtime_execution_id。
因此不得按runtime_execution_id是否为空决定lease存储；版本路由见DIRECTOR_RUNTIME。
不增加control_storage镜像列：冻结state_schema_version+engine registry唯一确定adapter，
未知或冲突绑定拒绝，而非查不到Control就fallback旧lease。

director_runtime_controls新增checkpoint_ref JSON_DOCUMENT?。NULL仅旧绑定或尚未完成首个安全边界；
非空形状{thread_id:String240,checkpoint_ns:String120,checkpoint_id:String200,state_hash:CHAR64,
engine_version:String120,state_schema_version:String120,lease_epoch:int>0,runtime_revision:int>0}。
JSON object与数值/长度由CHECK加typed端口校验；ref中的execution/Turn/project从thread_id解析严格等于该Control，
state版本与冻结绑定相同。更新只在当前lease/epoch/CAS与Turn投影同事务发生，
不得把旧epoch写入提升为当前；指针引用私有checkpoint，不复制正文到应用库，不跨schema加业务FK。

director_runtime_signal_claims新增request_hash CHAR64?、outcome String16? CHECK NULL/applied/obsolete、
applied_runtime_revision Integer?、settled_at timestamptz?。旧行hash可空只用于核对已有字段，
新claim必写hash。outcome=NULL要求后两列NULL；applied要求revision>0与settled_at非空；
obsolete要求settled_at非空、revision可空。原reason/reference/expected_revision/首次lease字段不可改。
新epoch可处理原未完成claim，但结果仅一次NULL→终值；一事务提升checkpoint/Turn并写applied，
重复只读原结果，不能因“已claim”误判“已执行”。仍沿该表原项目RLS，无新通用事件任务表。

Turn.intent_snapshot.purpose是受服务端约束的冻结判别：user_request/supervision/flow_step。
supervision须master_run_id非空；flow_step须business_flow_step_attempt_id非空；旧missing为旧记录，
不补造监督目的。SQL CHECK限定存在时合法，改写purpose由不可变触发器拒绝。
新增部分UNIQUE(master_run_id) WHERE purpose='supervision' AND status IN
('queued','thinking','awaiting_user','awaiting_execution')；
部分UNIQUE(business_flow_step_attempt_id) WHERE purpose='flow_step' AND同非终态集合。
用户Thread槽只对user_request且queued/thinking约束(thread_id)，不包括等待用户状态；
补索引时先检查旧活动数据，存在冲突阻断，不取消别人的Turn来制造唯一性。

本回填是D2设计经D3恢复审查后的修订：复查新增JSON/索引/NULL与旧身份保留，表数仍27，
没有新增Runtime、根checkpoint、租约表或生产事实表。I2b需真实故障注入与PG约束证明，
不能以本段设计审查代替实测。

### D4回填：定位、处理证据与检索投影（未实施）

SourceExtraction.extraction_schema_version=2用于新0-based locator；原native-text-v1的位置是1-based，
转换显式减一并保存原locator，不能把旧数字原样当新版位置。不同schema版本不得混读。
SourceExtraction增加processor_evidence JSON_DOCUMENT N default {}，新schema2必须非空object；
形状{schema_version:1,processors:[{ref,engine,version,settings_hash,binary_sha256?,model_sha256?,
network_mode:local|external,invocation_id?,operation_id?}],coordinate_system:{index_base:0,bbox_origin:top_left}}。
真实CLI/权重版本、调用证据与所属project由服务核对，缺失不能填虚构hash或声称已验处理。
原parser_key/version仍表达整条解析合同，processors记录实际组成，不形成第二任务状态。

SourceFragment增加processor_ref String80 N、extraction_method String24 N CHECK
native_text/ocr/transcript/visual_input/metadata，evidence_meta JSON_DOCUMENT object N default {}。
processor_ref须在所属Extraction.processors存在；由约束触发器验证，JSON无独立FK。
evidence_meta仅含原locator/转换版本、旋转或EXIF坐标变换、可用置信度与warnings；
不容任意工具指令或凭据。locator.kind必须等于locator_kind（CHECK），body大小仍受已冻结处理档约束。

paragraph/table_cells locator增加可选part_path/container_key；DOCX必须包含受支持包内part，
container_key区分正文/脚注ID/表格ID/格内段，防止所有part的paragraph=0混为同一位置。
part只作为ZIP内标识，严格白名单解析，不传给宿主文件系统。table_cells的sheet在XLSX为真实sheet名，
在CSV/TSV为固定数据表名，DOCX使用table:<index>并带part/container定位。
图片/PDF/视频区域与时间窗保留坐标变换，UI按同一变换展示；不能重复0/1-based转换。
visual_input允许text_content为空，表示可定位图像输入；它不证明OCR或语义研究已完成。

ResearchCitation.quote须与Fragment方法一致：原生文本/OCR可显示片段原样，
transcript显式标机器转写，visual_input不能伪造逐字引文。跨schema引用必须携带该Fragment的真实版本，
历史未能可靠转为新定位的内容保持legacy限制说明，不静默丢弃。

research_result_revisions与knowledge_revisions各增加search_text Text生成列：
GENERATED ALWAYS AS(app.research_search_text_v1(body,标题或空字符串)) STORED。
该IMMUTABLE函数只抽取本行固定文字字段（text/title/description/display_name/aliases/interpretation/
scope_note/time.label及timeline各项文字），排除UUID/哈希/策略/内部key；不能查其他表或当前权限。
用确定性Unicode/空白规则归一化，函数v1语义冻结；改规则以新函数/重建投影合同执行，不篡改revision正文。

迁移在已有PostgreSQL内启用pg_trgm（无新服务），为search_text建立GIN gin_trgm_ops，
研究索引仍由project与Result.current指针限定，知识索引由owner及published Entry.current限定。
可另用表达式B-tree索引规范化标题/显示名做短名称精确查询；索引字段是派生投影，不允许客户端直接写。
应用运行角色不获CREATE EXTENSION/函数owner权限，生成函数不接收SQL/正则代码。
源撤回/指针变化即刻限制检索，不等待索引物理清理才生效；性能测试必须在真实PG中带RLS/当前指针执行。

本回填不增加表（仍27张），也不增加新Run/解析任务事实；块级中间对象位置/hash归Flow Attempt回执，
完整Extraction只在要求块全部完成后原子发布。D7补这些列/函数/索引的实际迁移与兼容检查，I4验证真实格式和CJK检索。

### D4回填：无项目知识事件的归属（未实施）

已读EventService/EventLog/Outbox/SseHub与0005/0009迁移：旧project_id=NULL事件允许通用读取，
且Redis SSE桥要求workspace_id。不能将新owner知识事件直接塞入旧NULL分支或以workspace_id=None订阅所有事件。

event_log、outbox_events、outbox_dead_letters增加scope_kind String16 N及owner_user_id UUID? FK users RESTRICT。
scope_kind=project/owner/legacy。project事件保持原project身份，owner_id为空；owner事件project_id必须NULL、
owner_id必须非空；legacy仅保留无法归属的历史NULL事件，禁止普通运行入口新建或广播。
现存project非空行迁移为project，旧NULL行先标legacy，不猜actor就是数据owner、不删除旧证据。
EventLog/DeadLetter历史project在合法硬清理后被原FK置NULL仍保留scope_kind=project，
不因此转成可全局读事件；新INSERT的project事件必须非空project，INSERT约束/服务守住该条件。

RLS替换旧NULL通配分支：
- project：project_id=current_project，且有可信当前项目归属；NULL历史项目对普通请求不可见。
- owner：owner_user_id=current_user且project_id=NULL。
- legacy：普通app无读写，只有明确维护/审查路径可核验。
同样限制WITH CHECK；应用不可改事件归属，EventLog保持追加写。Outbox仅允许现有投递状态字段更新，
DeadLetter重放必须原scope，不从请求payload重建owner。索引EventLog(owner_user_id,occurred_at,event_id)
及Outbox/DeadLetter按owner的查找索引，现有pending索引保留。

窄pending_outbox_event_contexts扩展返回scope_kind和DB确定的owner：project从Project→Workspace链，
owner直接用持久owner_user_id并核对User有效；legacy排除普通自动发布并报告scope_unknown数量。
Worker按该scope设置GUC后处理，不信payload里的owner。Knowledge变更与owner事件同事务，
不要求先创建一个假Project来获得通知。

SSE新增明确OwnerEventScope或WorkspaceEventScope，均由已认证身份构造；禁止用None表示跨用户全读。
缓冲重放、Last-Event-ID未知回退与Redis桥每次都先按scope过滤。知识/公共库通知使用
institution.facts.v1既有Redis上的独立topic/stream，project生产事件仍使用原production.facts.v1；
不把新知识通知伪装生产成功事件。公开payload只有对象/版本/变更种类，不带私有来源正文或地址。
同owner各Workspace都收到其共享库失效通知，异owner永远不可收到。
事件丢失时HTTP读取current事实仍正确，UI通知不是权限权威。

这只扩展原事件事实，不新增第二Outbox或通知服务。实现前必须一起更新所有writer/终态触发器/
发现函数/死信重放/Redis桥/SSE路由及其RLS/重放测试；不能只加owner列而保留旧NULL通配策略。

### D5回填：路由证据、采用回执与多模态（未实施）

provider_destination_revisions增加route_manifest JSON_DOCUMENT object N，显式包含
{schema_version:1,gateway_origin?,processing_origin,proxy_origin?,result_origins:[],allowed_redirect_origins:[]}；
processing_origin必须等于upstream_origin（CHECK），origin仅scheme/host/port，不存query/token/凭据。
声明hash覆盖完整manifest、processing_location与绑定配置hash；不允许通配任意目标。
动态未知结果origin停止自动访问，取得明确目的地许可后才恢复原任务，不重建Create身份。
旧真实目的地证据不足保留unknown，不从Proxy本地地址回填local。

D5原候选把采用回执放PublicAssetPublication；D7核对实际promote后改为AssetVersion唯一拥有，
因为私有/手工版本采用也需要回执，却不能因此强制建公共发布。目标增加AssetVersion：
adoption_request_key String160?、adoption_request_hash CHAR64?、accepted_asset_revision Integer?>0；
三列同空/同非空，部分UNIQUE(project_id,adoption_request_key) WHERE key非空，采用后不可改。
PublicAssetPublication不再重复保存这三列，通过source_asset_version_id读取原采用事实。
采用服务在Asset锁下先查同请求hash回执，再校验候选及expected_asset_version；正式current/Asset.version、
AssetVersion回执、符合公共采用条件的Publication/Items与事件同事务。回放返回原accepted版本，不以后来current冒充。
原from-artifact.creation_request_key继续表述Asset创建；采用key为`adopt:<sha256(创建命令规范身份)>`，
不直接拼接160字符原key造成溢出，也不要求用户提交第二次采用。历史formal数据不自动补造采用授权或入库。
candidate创建另增AssetVersion.creation_request_key/hash与created_asset_revision（Integer?>0），三列可空且同空/同非空，
及(project_id,creation_request_key)部分唯一，
保存不可变创建身份，与采用是两个事实。新建项目变体复用Asset创建request_key；给现有Asset创建候选复用版本创建键。
历史NULL不补造请求；未来新用户创建/采用均要求显式键，先鉴权再回原回执。metadata/引用变更不修改这些历史字段。

多模态不新建调用/附件真相表：AgentMessage/TextMessage扩展受profile控制的media_parts；
Invocation.request_snapshot保存SourceMediaRef、版本、处理方法、最终字节hash/数量及同源egress_admission，
不把原媒体base64复制为长期公开日志。SourceMediaRef依源类型由服务核验，不声称JSON有FK；
非法跨owner/源修订/未发布公共项直接拒绝。Gateway引用仍版本化，新增chat_tools_vision_v1必须更新
现有严格profile枚举和所有管理/registry/冻结消费者，不另建平行连接身份表。

ProviderOperation/Invocation/token的egress_admission是单次发送准入冻结证据；
首次NULL→object只在可信准备/发送边界允许，之后不得改写/清除。更新JSON其他诊断键不能绕过冻结，
由领域服务白名单与约束触发器检查。Provider返回request_summary不能覆盖服务器保留字段。
拒绝/未知后新用户操作必须新身份，旧证据不重置；声明明确未发送的传输重试规则见MODEL_PROVIDER。

元数据变体引用既有base_public_asset_link时不建立指向外项目Artifact的本地AssetVersionReference，
由统一引用解析器解析原public item；编译指纹同时绑定variant与源Reference身份。
D2的本地Reference复合FK继续有效，source/consumer双身份在令牌/来源闭包里保持。
本回填不增表，仍27张；I3/I5/I8需验证所有不可变、并发与拒绝零发送用例。

### D5回填：可配置语音与分段（未实施）

此前D5候选为ProjectCreativeProfile.voice_defaults和Shot持久模型覆盖；该两项尚未实施，
由下文D6三级配置统一收敛到ProductionModelProfile项目行，不再新增voice_defaults列。
Shot.director_state.voice保留音色/语速等创作输入，模型选择按D6本次指定或项目默认，不建立第四个隐含来源。
新显式voice_id参数记录options_binding_id作为兼容身份；它只能使不匹配参数阻断/待重选，不能反过来选择模型。
旧显式音色没有可证明身份时要求核对，不因另一模型有相同字符串ID就宣称声音相同；已冻结旧VoiceSpec只读不改。
选择只保存绑定ID、音色、语速/声明允许参数，不放Key/任意URL；按N06空对象表示未配置并提示设置，
不再回退部署TTS_ENGINE/TTS_VOICE、Edge或eSpeak。Edge历史身份仅可只读，不支持新Create。
每次执行重新解析当前本Workspace绑定并冻结VoiceExecutionSpec；不运行时换默认。

VoiceExecutionSpec的provider_binding分支必须完整保存Binding/连接/凭证/Catalog/Manifest/Compiler/
destination修订及请求格式/规范化版本，其他引擎分支不得携带这些字段。实际请求和恢复仍在原Operation，
不新建音频调用表或恢复退役通用音频槽。Provider ModelCapabilityManifest扩展既有voice.generate操作合同，
配置/目录/预检/模型支持生成器同步，单纯media_kind=voice不等于已可执行。

长文本在计划中冻结chunk ordinal/源文本范围/字节hash/voice spec及最大操作数；每段一个voice NodeRun，
最后本地voice_concat Node消费有序已完成音频Artifact。其输入快照保存段NodeRun/Artifact/hash/顺序，
输出单一规范化WAV，沿原Artifact血缘及计划用户门。拼接失败不再合成，未知段不重发。
现有非空node_run_id唯一Operation索引保留；“同Node多Operation”旧示意不得当当前能力。
这些是既有Graph/节点合同扩展，不新增表/Runtime。D7定义相应命令及D6项目媒体配置扩展迁移；
I8/I9验证实际bytes/时长/字幕、配置身份、拒绝零发送和段级恢复。

### D6回填：三级配置的项目唯一来源（未实施）

复用production_model_profiles项目行，不新增表，27张新表清单不变；这是N08范围内工程设计选择，待D8整体冻结。
不新增ProjectCreativeProfile.voice_defaults，不恢复audio.tts槽。现有项目唯一约束与version CAS继续使用。

| 新列 | 类型/null/default | 约束与语义 |
|---|---|---|
| media_config_version | SMALLINT N default 2（迁移回填另见下述） | CHECK IN(1,2)；1为尚待核对的旧配置，只可读/恢复历史；新媒体生成要求2 |
| image_model_binding_id | UUID Y default NULL | 图片默认，NULL为未配置；Binding media_type=image/purpose=keyframe |
| video_model_binding_id | UUID Y default NULL | 视频默认，NULL为未配置；Binding media_type=video/purpose=video |
| voice_model_binding_id | UUID Y default NULL | 新语音默认，NULL为未配置；Binding media_type=voice/purpose=voice（目标语音接入合同，不是现有已开放枚举） |
| voice_options | JSON_DOCUMENT N default {} | JSON object，allowed voice_id/speed/response_format/instructions，逐Manifest限制；无绑定时必须{} |

三Binding各建`(workspace_id, binding_id)→provider_model_bindings(workspace_id,id)`复合FK RESTRICT；
在被引用表补唯一候选键。非空绑定对应purpose/media_type的归属由共享验证及约束触发器拒绝，
不能仅以UI选项限制；Binding类型/归属在被引用时不可改写。连接可停用但不级联清除项目选择。
profile的`(workspace_id,project_id)→projects(workspace_id,id)`复合FK及候选键补齐，现有project_id唯一保持。
三个Binding列分别建部分索引（非NULL），供停用影响查询；沿原Profile RLS及选择Workspace/Project Owner授权，
不因平台页面名称扩展权限。workspace-level profile须三Binding全NULL、voice_options={}。

目标`bindings`只持有文本planning.*，媒体新写禁止visual.*/video.*键；项目默认和同次快照不双写。
media_config_version=2时用CHECK/受限JSON键验证禁止旧媒体键；版本1只为隔离待核对数据，不能成为新执行分支。
迁移先给旧行赋1，不直接应用2的默认；纯文本且无待核对媒体的行可显式验证后设2。
旧媒体项转换前保存可核对证据与备份；迁移不会删除旧未知执行或凭据。转换完成后的历史配置证据
仅作审计/回退依据，不参与新解析。实例清理若涉及旧业务数据，先走主合同硬门；本任务当前不执行。

一行CAS覆盖三默认、语音选项与planning文本patch；原version positive保持。创建无行使用expected_version=0，
并发创建由project唯一约束+事务转409，不默默copy workspace默认。更新必须匹配version。
版本1的旧配置只能通过同一项目配置命令显式核对：提交旧来源review_fingerprint和三个目的的选择/清空，
服务端核对全部冲突已关闭后在同事务置media_config_version=2；指纹或来源变化继续409，不能永久困在只读无修复入口。
保持更新者/时间审计；配置PUT是版本化替换，重复旧版本提交返回409且不新增版本。
响应丢失先GET核对当前值/版本，不自动以新版本再写；不声称当前Profile已有持久request_key回执表。
本次配置保存零Provider操作，不为它新建Runtime或可变镜像表。
配置变更只发对应project事件，预览消费者失效重读；不向其他owner广播绑定名称或凭据。

旧ProjectProviderBinding及Profile媒体键仅在迁移核对阶段可读；切换完成不保留双写与fallback。
单次requested_binding_id/参数沿原请求和执行快照保存，无单次默认表；已提交请求不受配置更新改写。
D7须补MC01–08的PG约束、权限、迁移冲突与API回执验证；当前没有Schema或实例变化。

### D7回填：公共浏览、创建回执与目的地声明（未实施）

采用回执位置已在D5回填段明确收敛为AssetVersion；Publication无重复adoption三列。
AssetVersion.creation三列绑定创建时Asset.version，adoption三列绑定采用时Asset.version，
分别是不同用户动作回执；两组各自有全空/全非空和不可变约束，不能用current行版本回放过去响应。
现有Asset.creation_request_key/hash继续负责新资产创建，同项目唯一；不新增通用资产命令表。
新AssetCreateReceipt的created_asset_revision为创建时常量1，后续改变从GET读取；候选创建单独保存其受理版本。

公共资格窄端口支持判别联合owner_preview与project_use：前者只给当前owner已发布且当前用途允许的单一item媒体，
后者额外要求消费project/link资格。都不返回源Project/NodeRun/Invocation/原件正文，不切源项目GUC绕过私有RLS。
SQL受限函数分别签名/参数检查，明确REVOKE PUBLIC；调用者只能传被当前owner可见Publication固定的item，
不是任意artifact/project ID。无需新表，需受限PG角色覆盖两分支及跨owner/撤销拒绝。

ProjectPublicAssetLink创建键/hash与源身份不可变。创建回执只含id/publication/created_version=1，
label/detached/version后续改变不改原创建意义。重复自然键但非原请求键返回既有链接冲突，不创建另一条回执假象。
PATCH标签/解除/恢复为单行CAS；重复旧version返回409，GET恢复，不假称有独立PATCH请求键表。

provider_destination_revisions追加：origin_expected_revision Integer N>=0、configuration_hash CHAR64 N、
location_evidence JSON_DOCUMENT object N；CHECK revision=origin_expected_revision+1，
UNIQUE(workspace_id,binding_ref,origin_expected_revision)。新的修订不可UPDATE，旧实例声明不能补造trusted证明。
binding_ref严格为`binding:<UUID>`或`gateway:<UUID>`（当前受管Gateway连接身份）；分别锁对应绑定/受管连接稳定行，
在锁内校验最新revision与配置hash，插入/重放，不能无锁MAX(revision)+1。同键同declaration_hash回原行，异hash409。
不存在合法对应对象的旧ref只作历史unknown，不允许新发送按字符串任意解析。
location_evidence判别形状：
- container_network_contract：{method, deployment_manifest_hash, network_policy_hash, verified_at}；
  local必须具备这两个真实hash并由可信部署核验产生；仅用户声明/localhost不足。
- external_configuration：{method, configuration_hash, verified_at}；真实受管配置明确指外部处理，hash须等于列值。
- unresolved：{method, reason_code}；processing_location必须unknown，不携带伪造的已验证时间。
local/external/unknown的允许证据组合由服务及JSON约束触发器检查；证据和route_manifest一起入declaration_hash。
发送前仍核验当前部署/配置是否漂移，数据库中的历史证明不自动成为永久通行证。
purposes及project policy的allowed_purposes只允许API D7的EgressPurpose枚举；SourceUse用途枚举保持独立。

SourceUse旧对象不存在subject时PUT expected0：Project锁下创建subject version1再写首条修订result_version2，
origin_expected_version记录内部1，request_hash仍绑定原HTTP expected0；重放先查项目request_key，不再建立subject。
不同key的expected0在subject已存在时冲突；GET missing仍零写入。SourceUse首条声明不能冒充过去的许可。

### D8补齐：解析重受理与有限生命周期（未实施）

旧ProjectFileService.retry_extraction实际复用EventLog.retry_key，目标沿该事实扩展，不加第二解析Job表。
project_file.extraction_requested schema2含request_key/hash/accepted_attempt/processor_profile_revision；
对该event_type+schema2建立(project_id,aggregate_id,payload.request_key)及
(project_id,aggregate_id,payload.accepted_attempt)表达式部分唯一索引，JSON字段类型由CHECK/服务校验。
Project→File→Revision锁内先查原事件回执再CAS版本/attempt；retry仅failed→pending，reparse仅parsed→pending，
两者attempt+1，旧Extraction/Analysis不删除。新Worker在冻结attempt/processor合同下完成，否则保留失败原因。
旧pending本地任务在维护窗口已确认写者停止后可记录中断失败/旧状态证据，随后显式retry；
不能没有排空证据就改状态、把旧队列事件绑定到当前attempt，或在Migration中重新分析真实资料。

I4-01已实施（迁移0109）：`project_file_revisions.processor_profile_revision`(String64?)在受理时冻结，
CHECK只允许NULL或64字符；Worker只在该profile等于当前`profile_revision`时执行，NULL（旧受理）以
`source_profile_legacy`失败等待显式retry，不等时以`source_profile_drift`失败。事件日志的schema2
`project_file.extraction_requested`增加部分唯一表达式索引`(project_id,aggregate_id,payload->>'request_key')`
与`(project_id,aggregate_id,payload->>'accepted_attempt')`（仅PostgreSQL，Alembic不比较表达式索引；
实际DDL在0109，`alembic check`无漂移已验证）。

KnowledgeEntry有限转换：draft经save_draft保持draft、publish→published、withdraw→withdrawn；
published仅publish→published或withdraw→withdrawn，save_draft拒绝；withdrawn允许save_draft→draft、
publish→published或新withdraw决定保持withdrawn。每个有效新决定追加Revision/version，
同key重放不增版本。发布/撤回要求完整已保存内容，初始化current=NULL只能在创建事务内完成，不作为已发布事实。
Publication初始按资格available/restricted；用户withdraw进入withdrawn，只有显式恢复才离开withdrawn，
恢复后依据实时来源资格变available或restricted。来源投影更新不得把用户withdrawn自动改回available。
SourceUse初始unreviewed，用户declared/revoked可在二者间显式切换；revoked用途为空，
重复状态的新决定仍是新审计修订，旧key重放不修改head；没有“清除历史回到未审”接口。
Result归档只改元数据/version，不删除current内容；无current的新发现归档同样合法，事件revision_id可NULL。
这些转换不新增状态真相，API/触发器/事件与相应回执遵守同一规则。

### D8补齐：资产生产目标与计划确认依据（未实施）

独立资产媒体生成复用Asset作为明确候选目标、ProductionGraph/NodeRun/Operation/Artifact作为生产事实，
不新增表，27表清单不变。Asset无current版本只表示尚未采用，不得从status=active推导已有正式形象。
ProductionGraph允许新增scope_type=asset、scope_entity_id=真实Asset.id；GraphService验证其同project归属。
为asset分支补约束触发器验证目标存在/同project，并在Asset硬删除时拒绝仍被Graph引用的记录；
不得声称多态scope_entity_id本身已有原生FK，也不为已有其它scope凭空改变语义。迁移预检未知旧scope值阻断、不猜测。
资产图片/视频/配音节点沿原注册合同，输入快照冻结asset/版本、约束、参数、模型、引用与来源闭包；结果不自动写正式AssetVersion。
已有Version/Graph的Asset.kind不可原地变成另一媒体类别，另建明确目标；空草稿变kind仍须CAS并重验预览。

ProductionCommandAuthorization增加target_kind String16 N default shot、asset_id UUID?，shot_id改可空；
CHECK target_kind=shot时shot非空/asset为空，asset时反之。分别以(shot_id,project_id)/(asset_id,project_id)
复合FK绑定原实体并RESTRICT保留已批准记录，补父候选键；旧行明确回填shot，不改原body/hash/执行身份。
body新schema含精确target且与列一致，typed服务及约束检查；旧body仅按旧schema读，不伪造asset授权。
原profile_version是ProjectCreativeProfile.version，保持语义；模型Profile版本在原冻结body内另有明确名称。
accepted状态仍要求原node_run_id，不能换目标、清回执或把已接受grant改成另一次批准；取消走原运行控制。
BusinessFlow asset步骤仍用project scope与typed asset输入；grant target、Graph scope、snapshot target三者一致且同project，
一个attempt仍最多一个NodeRun，不扩Director scope枚举。

已采用AssetVersion正文及Reference成员集合不可再更新/追加/删除，仅允许既有formal→historical生命周期状态变化。
from-artifact应先在同事务构造candidate/References再通过统一采用服务冻结，而不是先formal再绕约束追加引用。
Reference写入需锁父Version并检查candidate资格，采用同一锁序；并发追加与采用不能产生未被预览/发布hash覆盖的成员。
新的设定或参考通过新候选版本再采用，原公共版本不跟随；历史formal未有新回执也不因此自动变回可写。
EditSession.timeline schema2新增API定义的Clip.source/audio_source判别引用；production_lineage仍由服务产生，客户端不可写。
其中selection_snapshot是服务器在Save时对选用来源的观测（schema/session_version/clip source/hash/确认身份与版本），
不是另一可写Formal事实；原initial来源信息保留。它与当前timeline/version同事务更新，导出时复制到原render输入快照。
来源未变时沿用合法原观察，来源改变必须查真实当前正式/已采用资格；触发器/服务拒绝跨项目或伪造source证明。
之后Shot当前Formal改变不重写旧快照；安全撤销/bytes不可用仍在每次新使用核验。客户端metadata中同名键不被当可信证明。
资产/公共源用固定版本和消费Link解析，JSON中的ID由typed服务及保存/编译校验，不声称JSON天然有FK。
最终render NodeRun.input_snapshot同时冻结这些来源与资格，Export仍只绑定同一不可变渲染快照，不复制源媒体所有权。
现有Shot-only时间线保留schema1解释，用户显式Save新版本后转schema2，历史导出不重算hash。

### D7迁移、切换与回退合同（设计，未执行）

基线源码103个revision、head 20261113_0099；实施时重新核对，以下M编号是依赖批次而非占用Alembic revision。
历史迁移不改写，不stamp跳过，当前head以前存在单向清理，验证只对新增批次选择合法downgrade边界。
必须先辨认实际数据库/角色/镜像/活动任务；C10未知时不能把空质量库迁移成功冒充现有实例可升级。

| 批次 | 变更及依赖 | 准入/回退边界 |
|---|---|---|
| M01身份与约束 | 既有projects/workspaces/assets/versions/references/artifacts/episodes候选键、跨项目组合约束；所有新增列先按历史真实性允许NULL | 查重/错配/孤儿清单为0才建约束；异常不自动删/合并；原身份与正式指针hash不变 |
| M02执行控制 | Run/Plan/Receipt、Flow/Step/Attempt、Turn关联、RuntimeControl checkpoint引用/epoch及SignalClaim结果 | 创建父表→子表→延迟循环FK→索引/权限；旧Agent只保留原读/停止路径，不迁移checkpoint冒充v2 |
| M03用途与外发 | SourceUse三表、目的地/策略三表、Invocation/Operation/token准入字段及事件显式scope | 先窄函数/角色，再新准入；旧NULL事件标legacy不可广播；旧操作不补造准入 |
| M04资料与研究 | Extraction/Fragment、ResearchResult/Revision/Citation、Analysis三表及文件current指针；依M01/M02/M03 | 既有提取确定转换，语义分析不在migration调用模型；启用新研究前控制/安全门必须实际通过 |
| M05知识与公共资产 | Knowledge三表+项目引用、Publication/Item/项目链接、变体/令牌双scope、两类采用/创建回执 | 私有SELECT继续拒绝，owner与项目RLS分别验证；不自动把历史formal发布公共库 |
| M06项目模型与语音 | Profile三个Binding/voice选项/迁移核对版本，voice能力/冻结Spec及引用消费者 | E04旧配置冲突清单，人工明确选择后ready；切换到新唯一写面，Edge新操作关闭，旧调用不重发 |
| M07分集与交付 | work_type/目标、EditSession分集/范围确认/创建键、Export四列绑定与复合RESTRICT | 旧作品类型/会话范围保留未确认，旧导出不伪造NodeRun/Timeline绑定；新导出必须新合同 |
| M08检索与切换核验 | 固定函数版本search_text/pg_trgm索引、事件writers/窄发现函数/完整权限、旧消费者清退 | 先验证数据及新读/写/恢复；有数据的新不可变表或旧列清理不得破坏性降级 |

M04与M05允许先建空结构，但不在M02/M03验收前接入真实机构资料或启用自动模型研究。
M07项目类型等基础列可在I1先增加；表中依赖用于约束引用/功能启用，不要求把所有SQL硬塞进一次大事务。
索引默认普通事务建索引并安排维护窗口；需要在线并发索引时另列独立迁移/失败清理，不能将CONCURRENTLY塞入默认事务。
不承诺滚动混跑旧应用：新增约束/事件scope/DTO切换后API、dispatcher和workers使用同一候选镜像，
先停止新接纳再排空/封锁旧执行，不能让旧writer继续写缺scope或缺准入的新数据。

#### native-text-v1确定转换

已实际读取source_parser：TXT存line；CSV/TSV存row/column/line_start/line_end；DOCX存part/paragraph或table/row/column/paragraph，均1-based。
转换逐个SourceExcerpt保留原text和原location，ordinal按旧数组顺序从0分配，绝不按非空项重新推算源行/段号。
char_start/end按原文本Unicode code point计数，不是UTF-8字节或JavaScript UTF-16单元；浏览器定位需显式转换，
含emoji/组合字符fixture验证，不为方便定位归一化或改写原文本/hash。

| 旧location | 新schema2 locator | 必须保存的依据 |
|---|---|---|
| TXT line=n | paragraph_start=n-1,end=n,char_start=0,char_end=len(text)，container_key=text-lines | original_location及转换合同版本；这是源行定位，不冒称语义段落 |
| CSV/TSV row=r,column=c | table_cells，sheet为固定CSV/TSV数据表名，row=[r-1,r)、column=[c-1,c) | 原物理line_start/line_end留evidence_meta，不把含换行单元格拆成多行事实 |
| DOCX part,paragraph=p | paragraph=[p-1,p)、char=[0,len(text))，part_path原part、container_key=body | 原包内part只作标识，不能传给文件系统路径解析 |
| DOCX table=t,row=r,column=c,paragraph=p | table_cells对应单元格；part_path原part，container_key包含table:t-1及cell-paragraph:p-1 | 同格多段保留各自ordinal与段身份，不压成一条伪引用 |

仅对真实parsed且原location类型/数值/原parser合同已知的行转换；空/未知/损坏位置返回安全ID清单并阻断该转换，
保留原值，不造页码/bbox/时间戳。processor_evidence记实际执行的迁移转换器版本/hash及原parser_version，
不伪造旧时OCR/ASR或模型证据。旧记录无法证明的完整覆盖标unknown/location限制，不能满足新research_ready谓词。
新Analysis不存在的旧项目仍是未研究；重新解析/研究是后续显式业务动作，不在migration内执行。
新快照文本/原定位/原件hash逐行比对通过，再切换唯一读取/写入；旧excerpts列的删除另有保留证据与审批边界，
不能在转换失败后以空数组代替原结果使Alembic继续。

#### 迁移验证与回退

隔离测试至少覆盖：空库到候选head、0099带合成代表数据到候选head、重复upgrade无额外变化、
中途失败事务回滚、NULL/重复/错项目样本明确阻断、alembic check无漂移、所有新触发器/索引/GRANT/FORCE RLS真实存在。
运行角色必须测试非owner、非superuser、NOBYPASSRLS、无继承owner；只检查ORM模型不能证明权限。
比对保护集：原件/媒体hash、旧Operation/Invocation模型身份/远端ID、正式指针、旧Thread/Turn/checkpoint、
已保存Timeline及导出绑定；不因本轮增加字段就改变这些既有事实。
同样核验新只读修订UPDATE/DELETE/TRUNCATE拒绝、跨owner/Project组合FK、部分NULL逃逸、同版本并发只有一次成功。

降级只在新增数据为空且没有新字段被业务使用的隔离库演练；检测到研究/公开引用/控制回执/新配置或新导出数据，
必须拒绝破坏性downgrade并报告依赖数，不能先删数据。代码回退不能重新启用旧Edge、新调用fallback或绕过strict策略。
已有新格式执行时保持同候选恢复能力，回退旧API之前要有只读/恢复兼容证明；没有证明选择修复前进。
备份恢复是隔离验证路径，不是“恢复备份即安全回滚”：真实恢复可能丢掉备份之后的已计费/已受理事实，
必须核对原操作差异并单独批准，不能恢复后自动跑旧队列。
清理旧列/旧业务数据、不可逆迁移、真实恢复仍在主合同人工硬门；N11统一工程不自动豁免这些动作。
