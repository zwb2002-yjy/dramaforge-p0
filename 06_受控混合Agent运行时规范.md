# DramaForge 受控混合 Agent 运行时规范（P0）

**状态：HISTORICAL / SUPERSEDED（旧 P0 Agent 运行时）**

> 当前 AI 导演、Skill 和双层工作流的唯一合同是 `docs/current/02-运行时与领域架构.md`。
**生效日期：2026-07-14**  
**同步基线：2026-07-14**  
**决策：P0 采用“受控混合编排”**

## 1. 结论与不可破坏原则

DramaForge 不引入能够自由选择流程、自由调用工具或直接写入业务状态的“总控 Agent”。现有 **Creation Experience Module** 继续作为快速模式唯一对外深 Module；LLM/专用 Agent 只完成受限、可校验的结构化推理，所有状态迁移、写库、预算、外部调用、物化和产物回写仍由领域 Module 的公开 Interface 执行。

```text
React 快速出片 / 专业工作台
  → FastAPI Creation Route
  → CreationExperienceService + 显式状态机 + 单一 Unit of Work
      ├─ CreationAgentRuntime（只读上下文 → 严格结构化结果）
      │    → ProviderAdapter(openai)
      │    → AgentRun 1:N ProviderOperation → CostLedger
      ├─ RuntimeScheduler（Outbox → Arq，可靠派发与补偿）
      ├─ Assets Command Module（剧本、资产、人工锁定）
      ├─ Production Command Module（Graph 草稿、发布 gate、NodeRun）
      ├─ Execution Module（预算、ProviderOperation、取消、成本）
      └─ Events Module（EventLog、Outbox、Redis Streams、SSE）
  → Arq default Worker（AgentRun 与 I/O）
  → Arq heavy Worker（媒体与本地一致性推理）
```

必须同时满足以下原则：

1. **生产事实源不变**：Project、资产、Production Graph、NodeRun、ProviderOperation、Artifact、Review、CostLedger 和 EventLog 仍是生产真相。
2. **创作过程分层**：CreativeBriefRevision、CreationPlan、AgentRun 只保存创作意图、可确认建议和规划过程，不能替代 Production Graph 或 NodeRun。
3. **Agent 无写入型工具**：P0 中模型不能直接写数据库、文件、NodeRun、ProviderOperation、Artifact、CostLedger 或 EventLog。
4. **副作用必须经过领域 Command**：MaterializationPlan 只是受限命令描述，只有 CreationExperienceService 能在确认后解释和执行。
5. **Provider 调用必须先授权成本**：包括 Brief、Plan 和格式修复在内的每次文本规划都受预算预占、用户授权和成本审计约束。
6. **人工值优先**：专业工作台保存值、人工锁定值和审核结论不能被 Agent 自动覆盖。
7. **可靠异步而非“提交后顺手入队”**：数据库状态、EventLog、Outbox 同事务提交；Arq 派发由可靠 Scheduler 消费 Outbox 完成。
8. **不可跨项目复用 Agent 输出**：AgentRun 不参与跨项目、跨用户缓存，P0 也不定义 `cached AgentRun`。

## 2. 从三个参考项目吸收与规避

| 来源 | 采用 | 在 DramaForge 的落点 | 明确避免 |
|---|---|---|---|
| ArcReel | 主 Agent 不做重活；显式阶段/审核 gate；副作用进入工具层；子任务返回结构化摘要 | 两级确认、Agent 只返回 Pydantic 输出、领域 Command 唯一写入 | SDK/MCP 成为业务真相；模型直接读写文件/数据库；主会话保留大量原文 |
| Jellyfish | Service-first；Agent/Executor/Workflow/Task 分离；状态语义分层；任务可追踪 | CreationExperienceService 编排、AgentRun 可追踪、Arq 薄 Job、Graph 仍是生产执行真相 | 多个 Service 隐式拼出状态机；将 AgentRun 与 NodeRun 混为同一任务 |
| ToonFlow | 可替换 Provider、版本化 Skill/Prompt、实时反馈 | ProviderAdapter、prompt/schema/context compiler 版本、Outbox/SSE 快照刷新 | 自由 Decision Agent、嵌套 LLM tool 调用、Socket.IO 作为最终状态、弱 XML 产物和无 Trace |

## 3. 深 Module、Interface 与 Seam

### 3.1 Creation Experience Module 的唯一对外 Interface

调用者只需要理解项目快照、确认 gate、成本授权和稳定错误码；上下文编译、模型重试、调度、跨 Module 事务和物化顺序都隐藏在 Module 内部。

```text
estimate_planning(PlanningEstimateRequest) -> PlanningCostEstimate
start_project(QuickProjectStart) -> ProjectSnapshot
request_brief_draft(project_id, BriefDraftRequest) -> ProjectSnapshot
refine_brief(project_id, CreativeBriefRefine) -> ProjectSnapshot
confirm_brief(project_id, CreativeBriefConfirm) -> ProjectSnapshot
request_plan_draft(project_id, PlanDraftRequest) -> ProjectSnapshot
confirm_plan(project_id, plan_id, CreationPlanConfirm) -> ProjectSnapshot
cancel_agent_run(project_id, agent_run_id, AgentRunCancel) -> ProjectSnapshot
request_generation(project_id, scope, budget_confirmed) -> ProjectSnapshot
get_creation_snapshot(project_id) -> ProjectSnapshot
open_workbench(project_id) -> ProjectSnapshot
resume_quick_flow(project_id) -> GuidedStep
```

所有写操作立即返回提交后的 `ProjectSnapshot`，不得同步等待模型结果，也不得流式展示模型思维链。前端收到 SSE 后只使 TanStack Query 失效并重取快照。

`ProjectSnapshot` 只增加最小 Agent 摘要：

```text
id, operation, status, target_revision_id, error_code,
updated_at, estimated_cost, actual_cost_read_model, next_actions
```

不得返回完整 prompt、完整模型响应、BYOK、Embedding、预签名 URL 或内部推理内容。`actual_cost_read_model` 是从 ProviderOperation/CostLedger 查询聚合的只读值，不是 AgentRun 的持久化第二真相。

### 3.2 内部 Module 与调用方向

- `creation/service.py`：创作状态机、确认 gate、乐观并发、顶层 Unit of Work 和跨 Module Command 编排。
- `creation/planner.py`：CreativeBriefAgent、CreationPlanAgent 的输入/输出合同以及不可变 prompt 版本；每次只完成一个聚焦推理任务。
- `creation/agent_runtime.py`：领取 AgentRun、编译上下文、创建预算预占和 ProviderOperation、调用 Adapter、校验/有限修复、以版本条件提交结果。
- `creation/context.py`：按白名单和固定顺序构造 CreationContext，记录 `context_compiler_version`、来源 revision 和 `context_hash`；不做自由检索。
- `runtime/scheduler.py`：消费已提交的 Outbox dispatch 事件并幂等投递 Arq；提供补偿扫描，不拥有创作或生产状态机。
- `workers/default.py`：只登记 `run_agent(agent_run_id, dispatch_generation)` 薄 Job；Job 建立独立 Session/RLS 上下文并调用 AgentRuntime。
- `assets`、`production`、`execution`、`events`：通过内部 Command Interface 接收共享 Unit of Work；不得由 Creation 直接写所属表。

唯一允许的依赖方向：

```text
Route → CreationExperienceService
CreationExperienceService → Creation internal implementation
CreationExperienceService → Assets/Production/Execution/Events Command Interface
AgentRuntime → Provider capability Interface
RuntimeScheduler → Arq Adapter
```

P0 不引入 LangChain、Agent SDK、MCP Runtime、向量数据库、跨项目长记忆、Agent-to-Agent spawn、第二队列框架或第二实时通道。

## 4. 用户流程、成本授权与无 Provider 降级

### 4.1 启动项目不等于授权模型调用

`start_project` 在同一事务中只创建：

- 正式 Project；
- `user_project_preferences(experience_mode=quick)`；
- CreativeBrief 聚合根和一个可手工编辑的初始 revision；
- EventLog 与 Outbox。

它不因为用户设置了项目预算上限就自动调用文本 Provider。前端可以先调用 `estimate_planning` 展示操作范围、最坏可接受费用、币种、模型能力和计价快照，再通过 `request_brief_draft` 提交一次性授权。

### 4.2 PlanningAuthorization

所有会产生真实文本 Provider 调用的命令必须携带：

```text
pricing_snapshot_id
estimated_max_amount
currency
budget_confirmed = true
authorized_operations
expires_at
```

服务端必须重新校验：

- 计价快照仍有效；
- 授权操作包含当前 operation；
- 项目预算仍足够；
- 只在用户已配置且具备能力的 BYOK Provider 集合内选择；
- PlanningAuthorization 签发后不可修改或删除；
- 一次授权不能被其他 AgentRun 重复消费，AgentRun 作为审计记录禁止硬删除。

一次 AgentRun 的预算预占按主调用、允许的 schema repair 和允许的 Provider 重试计算最坏可接受费用。修复或重试会超过预占时必须停止，不得先调用再补确认。

### 4.3 无 Key 或文本 Provider 不可用

文本 Provider 是可选能力。没有可用 Key 时：

1. 正式 Project 和手工 Brief 仍可创建、编辑、保存；
2. 不使用隐式平台 Key，不跨账号代付；
3. AgentRun 不应进入无限 queued，而是进入 `failed`，错误码 `TEXT_PROVIDER_CONFIGURATION_REQUIRED`；
4. 快速模式提供“配置 Key”“手工填写 Brief”“进入专业工作台”三个确定动作；
5. 已确认 Brief/Plan 和人工内容不因 Provider 失败而回滚或被覆盖。

## 5. Creative Brief 与 Creation Plan 的不可变来源

### 5.1 CreativeBriefRevision

`creative_briefs` 表示项目内的 Brief 聚合；新增 `creative_brief_revisions` 保存不可变内容：

```text
creative_brief_revisions
- id
- creative_brief_id
- project_id
- revision_no
- supersedes_revision_id nullable
- source_kind: user | agent | imported
- source_agent_run_id nullable
- source_text
- brief jsonb
- status: draft | awaiting_confirmation | confirmed | superseded | cancelled
- confirmed_by / confirmed_at
- content_hash
- created_by / created_at
```

约束：

- `(creative_brief_id, revision_no)` 唯一；
- `brief` 始终通过禁止 extra 的 `CreativeBriefContent` 草稿 Schema；`start_project` 可保存字段固定但内容不完整的手工初始 revision，Agent 输出与 `confirm_brief` 必须再通过 `CompleteCreativeBriefContent` 完整性 Schema；`source_text` 与 `content_hash` 创建后不可更新；
- 编辑或 refine 必须创建新 revision，而不是覆盖旧 JSONB；
- 每个 Brief 聚合最多一个 current revision；
- confirmed revision 可以被新 revision supersede，但其内容和确认记录永久保留；
- `source_kind=agent` 时 `source_agent_run_id` 必填且一个 AgentRun 最多产生一个 revision；
- AgentRun 只能回链自己基于目标 revision 产生的新 revision，不能修改或复用已有 revision。

### 5.2 CreationPlan

CreationPlan 必须引用具体不可变 Brief revision：

```text
creation_plans.source_agent_run_id nullable UNIQUE
creation_plans.source_brief_revision_id NOT NULL
creation_plans.context_hash NOT NULL
creation_plans.materialization_schema_version NOT NULL
```

Plan 的 Agent 输出必须通过 `MaterializationPlanInput` 判别联合严格 Schema 并写入新 Plan；`source_agent_run_id` 必须唯一回链产生它的 AgentRun，手工 Plan 为 `NULL`，不得复用已有 Plan 或覆盖另一个 Plan。Plan 的来源 AgentRun、Brief revision、context hash 与 schema version 创建后不可变。`awaiting_confirmation` 的人工编辑必须通过乐观锁生成新版本并写 EventLog；`confirmed` 后内容不可变，后续修改必须创建新 Plan，并将旧 Plan 标记为 `superseded`。

### 5.3 两级确认

1. Brief Agent 成功后创建不可变 Brief revision，状态为 `awaiting_confirmation`。
2. `confirm_brief` 使用 `expected_revision_no` 和 `content_hash` 确认该 revision。
3. Plan Agent 绑定 `source_brief_revision_id + context_hash`。
4. Plan 成功后进入 `awaiting_confirmation`。
5. `confirm_plan` 锁定 Project、Brief revision 和 Plan，确认来源仍是允许物化的版本。
6. 任何晚到 Agent 输出若目标 revision、Plan version、人工锁定或 context hash 已变化，AgentRun 转 `stale`，不得写回。

## 6. AgentRun 状态机、可靠调度与取消

### 6.1 状态

```text
queued
  → running
  → cancel_requested
  → succeeded | failed | stale | cancelled
```

所有新 AgentRun 必须以 `queued` 插入。允许迁移：

- `queued → running | cancelled | stale | failed`
- `running → succeeded | failed | stale | cancel_requested`
- `cancel_requested → cancelled | failed`
- 终态不可反向迁移；Service 使用版本 CAS，数据库触发器必须拒绝列表外迁移和终态复活。

若 Provider 在取消后实际完成：ProviderOperation 和 CostLedger 如实记录成功与费用，但 AgentRun 最终为 `cancelled`，不采纳模型输出，不创建 Brief revision/Plan，也不触发后续规划。

### 6.2 事务 Outbox 到 Arq

创建 AgentRun 的业务事务必须同时写：

```text
EventLog: creation.agent_run.queued
Outbox: runtime.agent_run.dispatch_requested
```

提交后 RuntimeScheduler：

1. 使用 Outbox lease 领取 dispatch 事件；
2. 以 `_job_id = agent-run:{agent_run_id}:{dispatch_generation}` 投递 Arq；
3. 重复事件只产生同一个逻辑 Job；
4. Redis 成功而 Outbox 未标记 published 时允许重复投递，由 job id 和 AgentRun CAS 去重；
5. queued 补偿扫描器重新发出缺失的 dispatch 请求；
6. 业务 Module 禁止直接 `arq.enqueue_job()`。

### 6.3 Worker 领取与崩溃恢复

AgentRun 增加：

```text
leased_until
locked_by
claim_count
dispatch_generation
next_attempt_at
version
```

Job 运行时以条件更新领取：

```text
status = queued
AND next_attempt_at <= now()
AND dispatch_generation = payload.dispatch_generation
```

Worker 崩溃后的恢复规则：

- Provider 请求尚未发出：lease 到期后可安全重新入队；
- Provider 请求明确未送达且 Adapter 标记 `safe_to_retry=true`：创建下一 ProviderOperation attempt；
- 请求可能已送达但结果未知：不得盲目重复调用，进入 `failed(PROVIDER_OUTCOME_UNKNOWN)` 或由支持查询/幂等键的 Adapter 对账；
- 终态或版本不匹配的 AgentRun，重复 Job 直接无副作用返回。

### 6.4 幂等取消

`cancel_agent_run`：

- queued：直接转 `cancelled`；
- running：转 `cancel_requested`，阻止新 ProviderOperation；
- 已发出远端请求：调用 Adapter cancel（若支持），并保留结果/费用对账；
- 重复取消返回同一快照；
- 取消请求、最终状态、Provider 响应和费用都写 EventLog/Outbox。

## 7. ProviderOperation、预算和成本的唯一真相

### 7.1 基数

```text
AgentRun 1 ── N ProviderOperation
NodeRun  1 ── 0..1 ProviderOperation（沿用现有 P0 规则）
```

每个真正发往 Provider 的 HTTP/SDK 请求创建独立 ProviderOperation：

```text
provider_operations
- node_run_id nullable
- agent_run_id nullable
- attempt_no
- purpose: primary | schema_repair | transport_retry | provider_fallback
- actual_provider
- actual_model
- request_fingerprint
- request_summary / response_summary
- token_usage
- provider_cost / currency
- status / timestamps / error
```

数据库约束：

```text
CHECK((node_run_id IS NOT NULL) <> (agent_run_id IS NOT NULL))
UNIQUE(agent_run_id, attempt_no) WHERE agent_run_id IS NOT NULL
UNIQUE(node_run_id) WHERE node_run_id IS NOT NULL
```

格式修复必须是新的 ProviderOperation，且 `purpose=schema_repair`；不能覆盖主调用记录。

### 7.2 AgentRun 不保存第二套执行事实

AgentRun 只持久化：

```text
requested_capability
prompt_version
output_schema_version
context_compiler_version
input_hash
context_hash
status / stable_error_code
result entity reference
lease / retry metadata
```

实际 provider、model、token 和成本只属于 ProviderOperation/CostLedger。AgentRun 的总 token、总成本和最终 Provider 仅在 Read Model 中聚合。`succeeded` AgentRun 必须且只能回链一个与 operation 匹配的结果：Brief 操作回链由该 Run 产生且 supersede 目标 revision 的新 revision，Plan 操作回链由该 Run 产生、唯一标记 `source_agent_run_id` 且绑定目标 Brief revision 的新 Plan；其他状态不得持有结果引用。

### 7.3 BudgetReservation 与 CostLedger

`budget_reservations` 支持 `node_run_id XOR agent_run_id`，一个 AgentRun 使用一个覆盖其允许尝试上限的预算预占。每个真实 ProviderOperation 分别产生至多一条 `cost_ledger.entry_type='actual'`。

必须满足：

- 预占、actual、释放和 adjustment 均 append-only；
- schema repair、失败调用和取消后费用都如实记录；
- 未发出 Provider 请求的 attempt 不产生 actual；
- AgentRun 结束后释放剩余预占；
- 真实费用超过预占时保留费用、记录原因、冻结后续真实调用并告警；
- CostLedger 的 project_id、AgentRun/NodeRun 来源、ProviderOperation 和 Reservation 必须属于同一项目。

## 8. MaterializationPlan：受限命令而非自由工具

### 8.1 P0 Schema

```text
MaterializationPlan
- schema_version = materialization-p0-v1
- source_plan_id
- source_plan_version
- operations[]

MaterializationOperation
- operation_key
- kind
- depends_on_operation_keys[]
- payload
```

P0 只允许：

```text
update_project_planning_fields
create_episode
create_scene
create_shot_draft
create_asset_draft
create_character_draft
create_production_graph_draft
propose_existing_entity_change
```

明确禁止：

- 删除任何正式实体；
- 更新/删除 NodeRun、ProviderOperation、Artifact、CostLedger、Review；
- 覆盖人工锁定值；
- 发布 GraphVersion；
- 发起真实生成；
- 使用未注册 command kind；
- 通过自由 JSON 字段表达 SQL、路径、URL 或工具名。

### 8.2 引用与创建顺序

新实体间引用只能使用稳定 `operation_key`，已有实体只能使用经过项目/RLS 校验的 UUID。每个引用必须恰有一种来源：

```text
existing_entity_id XOR operation_key
```

Materializer 先验证完整计划，再按依赖拓扑执行：

```text
Project planning fields
→ Episode
→ Scene
→ Shot draft
→ Asset/Character draft
→ ProductionGraph draft
```

`operation_key` 在同一 Project + Plan 内唯一，并作为物化幂等键。重复 `confirm_plan` 必须返回已经创建的同一实体，不能重复插入。

### 8.3 Project 与 Graph 语义

Project 已在 `start_project` 创建，因此 Materialization 只能更新允许的规划字段，不能再次“创建 Project”。

Plan 确认时可以创建 ProductionGraph 和 draft GraphVersion，但不得发布。只有 Shot 审批、canonical Reference、人工锁定、DAG 校验和预算 gate 全部满足后，Production Module 才能通过自己的公开 Interface 发布不可变 GraphVersion。

`propose_existing_entity_change` 只创建可审阅建议，不自动应用；人工采纳必须走对应领域 Module 的显式命令。

## 9. confirm_plan 的单一 Unit of Work

`CreationExperienceService.confirm_plan` 是外层 Application Module 和唯一事务拥有者：

```text
BEGIN
  lock Project / BriefRevision / Plan
  validate permission, version, budget authorization and locks
  validate complete MaterializationPlan
  AssetsCommandModule(..., shared_uow).flush()
  ProductionCommandModule(..., shared_uow).flush()
  mark Plan confirmed/materialized
  EventsCommandModule(..., shared_uow).flush()
COMMIT
```

内部 Command Module 必须：

- 接收同一个 AsyncSession/UnitOfWork；
- 只 flush，不 commit；
- 不开启独立事务；
- 不直接 enqueue Arq；
- 不直接发布 Redis/SSE；
- 失败时让外层事务整体回滚。

任何 materialization operation 失败都不能留下半成品 Episode、Scene、Shot、Asset 或 Graph，也不能把 Plan 标为 confirmed。

## 10. Input Hash、Context Hash、单飞和复现

### 10.1 Agent input_hash 固定材料

```text
project_id
operation
目标 Brief revision / Plan ID 与 version
规范化用户指令
requested_capability
prompt_version
output_schema_version
context_compiler_version
context_hash
```

不得纳入时间、AgentRun ID、展示顺序、重试次数和前端临时状态。

### 10.2 单飞边界

P0 只允许以下范围单飞：

```text
同一 project_id
+ 同一 initiated_by
+ 同一 operation
+ 同一目标 revision/version
+ 同一 input_hash
+ 同一 context_hash
```

重复提交必须返回已有的 active AgentRun；数据库必须使用部分唯一索引覆盖 `queued/running/cancel_requested`。

P0 禁止：

- 跨项目复用；
- 跨用户复用；
- 仅因 hash 相同就复用旧输出；
- 创建 `AgentRun(status=cached)`。

### 10.3 可审计复现

AgentRun 必须保存不可变来源引用：Brief revision、Plan version、prompt version、schema version、context compiler version、ProviderOperation 列表和结果实体引用。普通业务列不保存完整 prompt/response；若合规要求保留调试材料，必须使用独立加密短期存储、最小权限和明确保留期，且不进入 SSE、Outbox 或普通日志。

## 11. RLS、项目一致性与 Worker 身份

### 11.1 RLS 覆盖

新增/修改表必须全部进入 RLS 矩阵：

- AgentRun、CreativeBriefRevision：直接 `project_id`；
- ProviderOperation：通过 `node_run_id XOR agent_run_id` 解析项目；
- BudgetReservation、CostLedger：直接 project_id，同时校验执行来源项目一致；
- Agent 结果、物化幂等记录和取消记录：直接或安全父链解析项目。

必须提供固定 search_path 的安全 scope 函数：

```text
app.project_id_for_agent_run(id)
app.project_id_for_provider_operation(id)
```

`project_id_for_provider_operation` 必须根据恰有一个执行来源解析，不能在 source 为空或双来源时返回项目。

### 11.2 Worker 身份

队列 payload 只可信任 `agent_run_id + dispatch_generation`，不能信任 payload 声称的 project/user/provider。Worker 必须从数据库重读 AgentRun，并以其项目和发起者建立：

```text
SET LOCAL app.current_user_id
SET LOCAL app.current_workspace_id
SET LOCAL app.current_project_id
```

工作区所有权或工作区 Provider 凭据在排队后失效时，执行必须失败，不能沿用排队时的权限快照。

## 12. Trace、事件、SSE 与请求标识

### 12.1 请求标识

- `correlation_id`：由后端生成，作为内部权威关联 ID，贯穿 HTTP、AgentRun、ProviderOperation、CostLedger、EventLog、Outbox 和日志。
- `external_request_id`：可从客户端 `X-Request-ID` 接收，经长度和字符校验后只用于排障。
- external_request_id 不得用于授权、RLS、幂等、租户判断或成本归属。

### 12.2 事件名称

状态与事件统一使用同一终态词汇：

```text
creation.agent_run.queued
creation.agent_run.running
creation.agent_run.cancel_requested
creation.agent_run.succeeded
creation.agent_run.failed
creation.agent_run.stale
creation.agent_run.cancelled
creation.brief.awaiting_confirmation
creation.brief.confirmed
creation.brief.superseded
creation.plan.awaiting_confirmation
creation.plan.confirmed
creation.plan.superseded
runtime.agent_run.dispatch_requested
```

事件 payload 仅携带实体引用、版本、状态、错误码、费用摘要引用和下一步动作；前端只能使 Query 失效并重取快照。

## 13. 稳定错误码与重试语义

P0 至少冻结：

| 错误码 | 自动重试 | 用户动作 | 已有确认内容 |
|---|---|---|---|
| `TEXT_PROVIDER_CONFIGURATION_REQUIRED` | 否 | 配置 Key 或手工编辑 | 保留 |
| `AGENT_BUDGET_NOT_CONFIRMED` | 否 | 确认费用 | 保留 |
| `AGENT_BUDGET_INSUFFICIENT` | 否 | 调整预算 | 保留 |
| `AGENT_PROVIDER_UNAVAILABLE` | 仅允许 BYOK 候选内受限降级 | 检查 Provider | 保留 |
| `AGENT_RATE_LIMITED` | 有上限、有预算时 | 等待或重试 | 保留 |
| `AGENT_TIMED_OUT` | Adapter 判定安全时 | 重试 | 保留 |
| `PROVIDER_OUTCOME_UNKNOWN` | 否 | 对账后人工重试 | 保留 |
| `AGENT_OUTPUT_INVALID` | 仅一次 schema repair | 手工编辑或重试 | 保留 |
| `AGENT_CONTEXT_STALE` | 否 | 基于新版本重试 | 保留 |
| `AGENT_TARGET_SUPERSEDED` | 否 | 查看当前 revision | 保留 |
| `AGENT_CANCELLED` | 否 | 可重新发起新 Run | 保留 |
| `AGENT_RUN_NOT_RETRYABLE` | 否 | 查看错误说明 | 保留 |

重试必须创建新的 ProviderOperation attempt；用户重新发起已终态 AgentRun 时创建新的 AgentRun，不能把旧终态 Run 改回 queued。

## 14. 安全与上下文规则

- CreationContext 只由后端从当前 ProjectSnapshot、明确的 Brief revision/Plan version、已审核剧本摘要、已锁定资产/Reference、预算/Provider 能力摘要和用户本次指令编译。
- 按字段白名单、稳定排序、长度上限生成 hash；记录每个来源实体 ID 和 version。
- 不读取任意工作区文件，不跨项目检索，不将历史聊天全文、其他项目、BYOK、Embedding、预签名 URL、内部审核证据或完整 Provider 回调交给模型。
- 模型输出未知字段一律拒绝；不得以 `extra=allow`、自由 metadata 或任意 JSON 绕过固定 Schema。
- 人工锁定和专业工作台保存值是只读约束；Agent 只能输出 `proposed_change`。
- Prompt injection 文本只作为数据字段进入模板，不得改变 system policy、工具集合、输出 schema 或命令白名单。

## 15. 可观测性

Prometheus/Grafana 至少新增：

- 按 operation/actual_provider/actual_model 的成功率和 p50/p95；
- queue wait、lease reclaim、dispatch 重放、queued 补偿数量；
- schema repair 率和每 AgentRun ProviderOperation 数量；
- stale 写回拒绝数、取消后晚到完成数、outcome unknown 数；
- token、actual cost、预占释放、预算阻断和超预占数；
- Brief/Plan 确认漏斗；
- 从 Plan 确认到首帧的耗时。

日志只记录 correlation_id、实体 ID、状态、错误码和脱敏摘要，不记录 Key、完整 prompt/response、Embedding 或永久对象 URL。

## 16. 必须通过的测试

### 16.1 单元

- Context 白名单、稳定 hash 和 compiler version；
- Prompt injection 不改变 schema/命令白名单；
- 严格结构化输出拒绝与一次 repair 上限；
- AgentRun 每个合法/非法状态迁移；
- MaterializationPlan 白名单、依赖拓扑和引用校验；
- 人工锁定不可覆盖；
- 错误脱敏和稳定错误码映射。

### 16.2 集成

- start_project 创建正式 Project，但未经预算授权不调用文本 Provider；
- 无 Key 时项目可继续手工编辑并返回确定动作；
- AgentRun、EventLog、Outbox 同事务创建；Redis 暂时不可用后可补偿入队；
- 重复 Outbox/Arq Job 不重复执行；Worker 崩溃前后按安全规则恢复；
- Brief revision 不可变；Agent 生成的 Plan 唯一回链产生它的 AgentRun，旧 Plan 可恢复其来源内容；
- Brief/Plan 两级确认、并发确认和重复确认幂等；
- stale/cancelled AgentRun 晚到输出不写回；
- 一个 AgentRun 的 primary/repair/retry 分别产生 ProviderOperation 和 actual ledger；
- AgentRun 不持久化第二套实际 provider/model/cost；
- confirm_plan 单事务物化，任一步失败无半成品；
- operation_key 重放不重复创建实体；
- ProviderOperation AgentRun 路径 RLS、跨项目 FK/触发器和 Worker 越权拒绝；
- Outbox 重放不产生重复 UI、费用或 Materialization。

### 16.3 Adapter 契约

- create/失败/限流/超时/取消/成本读取；
- `safe_to_retry` 分类；
- 支持时传递 Provider 幂等键；
- 仅在用户已配置且具备能力的 BYOK 集合内降级；
- request/response 摘要不含密钥和完整敏感内容。

### 16.4 E2E

```text
创建正式 Project
→ 展示并确认文本规划费用
→ Brief 生成/人工编辑与确认
→ Plan 生成/人工编辑与确认
→ 确定性物化到同一 Project
→ 进入专业工作台
→ 补齐 Reference / Shot 审批
→ 发布 GraphVersion
→ 首帧生成
→ 人脸检查 / 成本 / Artifact / SSE
```

还必须覆盖：SSE 断线后以 `Last-Event-ID` 接续并重取快照；专业模式人工锁定后返回快速模式只展示建议；无文本 Key 全程可切换手工路径。

## 17. 实施顺序

1. **ADR 与状态/错误码冻结**：AgentRun 状态机、调度恢复、预算授权、Brief revision、Materialization 命令、取消和错误码。
2. **数据迁移**：agent_runs、creative_brief_revisions、creation_plans.source_agent_run_id、AgentRun 状态迁移守卫、执行来源 XOR、1:N ProviderOperation、预算/成本、RLS、索引和触发器。
3. **可靠 Scheduler**：Outbox dispatch、Arq job id、lease、补偿扫描和崩溃恢复。
4. **Agent Runtime**：Context Compiler、ProviderOperation attempts、严格 schema、一次 repair 和条件写回。
5. **确认与 Materialization**：两级卡片、单一 Unit of Work、operation_key 幂等、Graph draft/publish gate。
6. **前端与降级体验**：成本授权、无 Key 手工路径、取消、错误动作和 SSE 快照刷新。
7. **治理与 S2**：Trace、成本、RLS、指标、runbook；真实文本 Provider 验收通过后再打通首帧垂直切片。

## 18. 冻结包同步约束

- `01_项目总需求.md` 冻结用户流程、P0 能力、验收边界与禁止项。
- `02_全栈技术栈锁定表.md` 冻结 AgentRuntime 文本能力边界、唯一 Arq/Redis 和可靠 Scheduler 技术实现。
- `03_全局目录规范.md` 冻结 agent_runtime、context、materializer、runtime/scheduler 与 Worker 的文件职责。
- `04_数据定义全集.md` 冻结 AgentRun、CreativeBriefRevision、PlanningAuthorization、1:N ProviderOperation、执行来源 XOR、预算/成本、RLS 与 DTO。
- `05_模块落地约束.md` 冻结通用 Unit of Work、Scheduler Interface、状态、重试、取消、锁定和 Materialization 落地规则。
- 本文与 01–05 共同构成 P0 六份冻结包；任何 Agent 运行时变更必须在同一变更集中同步更新受影响文档、ADR、迁移、OpenAPI、夹具与验收记录。

任何实现必须遵守本文；不得引入自由 Agent、写入型工具、第二队列、第二实时通道、跨项目长记忆或未审计 Provider 调用。
