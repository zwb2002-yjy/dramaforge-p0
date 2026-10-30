# Director Agent：当前实现与职责审计

Status: current-reference。本文是 [DIRECTOR_RUNTIME](../DIRECTOR_RUNTIME.md)、
[PRODUCTION_RUNTIME](../PRODUCTION_RUNTIME.md) 与 [ARCHITECTURE_MAPPING](../ARCHITECTURE_MAPPING.md)
的详细源码视图，不建立第二套领域权威。目标接口见 [目标架构](DIRECTOR_AGENT_TARGET_ARCHITECTURE.md)，
未实现工作见 [实施计划](DIRECTOR_AGENT_IMPLEMENTATION_PLAN.md)。这不是发布验收记录。

源码同步日期：2026-10-07。模型目录与协议合同已改为文件加载，媒体统一使用具体 Binding、冻结 WorkbenchExecutionPlan 与 ExecutionIdentity；
未接入执行的第二套 Cutover / Policy / Handler 存储和预检已删除。
这些变化不等于本文讨论的 Agent Loop / ToolRegistry 已实现，能力细节见
[模型指南](MODEL_CAPABILITY_PROMPT_COMPILER.md) 与 [模型权威](../MODEL_PROVIDER.md)。

## 1. 明确结论

**当前 Director 是结构化 LLM 建议/提案服务，加上可持久恢复的确定性编排；尚不是 LLM 自主选择领域工具的通用 Agent Loop。**
已有文本模型调用、一次 schema 修复、调用日志、提案、显式决策、授权、checkpoint 和恢复不能被忽略；
但这些不能证明已具备 `LLM → 任意获准工具 → ToolResult → LLM` 的闭环。

直接依据：

- [text_model.py](../../backend/app/director/text_model.py)：`TextModelPort.generate` 已是 session-free 模型执行 seam；`CapabilityTextModel` 将明确的 model_id 交给 CapabilityRouter。
- [text_transport.py](../../backend/app/director/text_transport.py)：`DirectorTextRuntimeAdapter.generate_structured` 由调用方指定任务、schema 与上下文；一次 primary，解析失败时同模型最多一次 schema repair；并非模型挑选工具。
- [text.py](../../backend/app/providers/contracts/text.py)：`TextGenerateRequest.tools` 已存在，但 `TextMessage.role` 仅 system/user/assistant，没有结构化 tool result 与 call_id。
- [litellm_adapter.py](../../backend/app/providers/litellm_adapter.py)：`_build_payload` 可发送 tools；`create` / `_extract_completion_text` 主要抽取文本，未将响应 tool_calls、finish_reason 归一成 Agent 响应。仅填 tools 不足以接通闭环。
- [langgraph_adapter.py](../../backend/app/director/runtime/langgraph_adapter.py)：图的边与节点固定；`_propose` 调业务 port，port 读取已存提案，不调用 LLM 生成。

因此不删除现有 Runtime，而是把“推理循环”与“跨用户/Worker 等待的流程位置”在契约上分开。

## 2. 当前真实调用链

### 2.1 文本任务：不是一个统一聊天入口

```text
ShotDirectorSuggestionPanel / 相关工作台
  → api/v1/director.py 的 suggestion / recommendation
  → ShotDirectorSuggestionService / DirectorRecommendationService
  → 读取 project、shot、版本与已获授权的上下文
  → DirectorTextRuntimeAdapter.generate_structured
      → DirectorContextBuilder.build（纯 JSON 冻结）
      → DirectorTurnService.create_or_get / claim（身份与 CAS）
      → ModelBindingResolver.resolve（项目/工作台模型绑定）
      → InvocationService（prepare / submission 状态 / 经验证输出）
      → TextModelPort → CapabilityTextModel → CapabilityRouter
      → LiteLLMModelAdapter → LiteLLM Gateway → 配置的上游模型
      → JSON schema 解析；必要时同模型一次修复
      → 持久化 invocation / turn 输出与证据
  → 类型化 Suggestion / Recommendation
  → 用户显式接受或保存；不是生成媒体
```

源码入口：[前端建议面板](../../frontend/src/features/director/ShotDirectorSuggestionPanel.tsx)、
[Director API](../../backend/app/api/v1/director.py)、[suggestion](../../backend/app/director/suggestion.py)、
[recommendation](../../backend/app/director/recommendation.py)。
Story 的调用方是 [StoryGenerationService.generate_proposal](../../backend/app/director/story_generation.py)，
Editing 的调用方是 [EditingDirectorSuggestionService.suggest](../../backend/app/director/editing_suggestion.py)；
两者复用同一 transport，但输出及提案消费不同。
不能把一个非持久 suggestion 等同于已持久的 `DirectorProposal`。

当前模型请求将 task、context、required_output_schema 放入 JSON user message；
system 明确禁止 SQL、凭据、Provider/runtime 字段和媒体执行命令。
这是固定任务的结构化调用，不是可自发现工具的聊天协议。

### 2.2 持久编排

```text
已持久 Proposal / 已验证 suggestion
  → DirectorRuntimeStartService.accept 或 DelegationService.accept
  → 引擎选择及不可变 Turn 绑定 + runtime wakeup
  → worker-director → DirectorRuntimeExecutor
  → LangGraphDirectorRuntime（仅获绑定的 langgraph Turn）
  → DirectorDomainRuntimeTools
  → 已有 Proposal / 决策 / Production authorization / ProductionFacts
  → RuntimeView → DirectorRuntimeProjector → DirectorTurn 外部投影
```

证据：[start](../../backend/app/director/runtime/start.py)、
[delegation](../../backend/app/director/runtime/delegation.py)、
[routing](../../backend/app/director/runtime/routing.py)、
[executor](../../backend/app/director/runtime/executor.py)、
[worker](../../backend/app/workers/director.py)、
[projector](../../backend/app/director/runtime/projector.py)。
只有 LangGraph 是可执行身份；缺失或不支持的身份拒绝执行，不迁移到另一种引擎。

### 2.3 图节点逐项审计

所有节点均**不直接调用 LLM**。下表的 proposal/decision/fact 是 checkpoint 中的序列化观察值，业务校验仍由 port 完成。

| 节点 | 输入 → 输出/位置 | 数据来源与副作用 |
|---|---|---|
| `propose` | RuntimeInput → proposal ref/version、awaiting_user，或已持久 decision | `DirectorDomainRuntimeTools.propose` 查 Turn、Proposal items、authorization；读取，不创建提案。step/revision 增加 |
| `await_decision` | interrupt → ResumeSignal → RuntimeDecisionFact | `decision` 查已存用户决策/事件/Proposal items；未全部决策则拒绝；不是直接信任 resume payload |
| `submit_execution` | request + proposal + stable command_key → receipt、NodeRun ref、awaiting_execution | 校验持久 authorization_ref 与 command_key；`ProductionAuthorizations.submit` 调现有受理链；这是业务命令副作用，不是直接 Provider HTTP |
| `await_execution` | interrupt → execution signal → terminal ProductionFact | 查 EventLog 后重读 `ProductionFacts.tracking`；校验 project/run；未终态拒绝。成功等确认，失败结束 |
| `confirm_candidate` | interrupt → 已持久用户决策 → completed | `decision` 读取决定/正式选择事件；节点本身不提升 Formal，不直接写 Artifact |
| `reject` | rejection → completed/proposal_rejected | 只更新流程位置 |
| `complete_without_execution` | 无执行的已接受提案 → completed/proposal_applied | 只更新流程位置；应用事实必须已存在 |

图拓扑：`START → propose → await_decision → submit_execution → await_execution → confirm_candidate → END`；
另有已决策跳转、reject 与 complete_without_execution 分支。
`max_steps` 是 workflow 步数护栏，不是“模型自主工具调用次数”。
`interrupt` 释放执行；不存在图中等视频完成的长时间 sleep。
完整依据：[图实现](../../backend/app/director/runtime/langgraph_adapter.py)、
[领域 port](../../backend/app/director/runtime/domain_tools.py)、[port 契约](../../backend/app/director/runtime/ports.py)。

### 2.4 生产主链

```text
用户显式执行 / 已持久的一次性导演委托
  → ProductionCommands.submit_user_execution / ProductionAuthorizations.submit
  → 锁定 scope、版本校验、稳定 command_key、请求哈希与既有 receipt 检查
  → WorkbenchExecutionService.build_plan / create_and_dispatch
  → ProductionGraph / GraphVersion / NodeRun + 冻结 plan/reference/model identity
  → transactional Outbox → dispatcher / scheduler → production Worker
  → execute_media_node_run → prepare_media_submission
  → Provider compiler（唯一 wire body 构造者）
  → ProviderOperation submission_started 持久提交
  → Provider Runtime submit / poll / resume
  → 媒体安全下载、校验、不可变 Artifact 与 lineage
  → Review / Candidate → 用户决策 → Formal
  → Production event → Director wakeup / reconcile → 流程恢复
```

代码：[commands](../../backend/app/production/application/commands.py)、
[authorization](../../backend/app/production/application/authorization.py)、
[workbench_execution](../../backend/app/production/workbench_execution.py)、
[product_path](../../backend/app/execution/product_path.py)、
[media_submission](../../backend/app/execution/media_submission.py)、
[provider_execution](../../backend/app/execution/provider_execution.py)、
[formal_selection](../../backend/app/production/formal_selection.py)、
[events](../../backend/app/production/application/events.py)、
[reconcile](../../backend/app/director/runtime/reconcile.py)。

`ProductionCommands.submit_user_execution` 明确要求可信用户输入；Agent 不能把它包装成无人确认的执行工具。
`prepare_media_submission` 在网络前持久化 submission_started，恢复需沿用已有远端任务/执行身份；
unknown submission 不等于可安全 retry。Director 不拥有上述生产状态，也不替代 Worker。

## 3. 状态所有权：重复字段不等于重复权威

| 对象/字段 | 当前性质 | 约束与风险 |
|---|---|---|
| `DirectorThread` / `DirectorMessage` | 会话事实 | project/scope 唯一 thread；不是模型 turn 调度器。当前 Turn 无 thread_id 外键，不能宣称已串起完整 Agent transcript |
| `DirectorTurn` identity、request_key、context_hash、input_versions | 业务轮次与冻结输入权威 | 保留现有 CAS、deadline、输出恢复；不用新的 AgentSession 重建 |
| 未绑定图的 Turn.status/revision | 业务观察与文本结果的状态事实 | 不可用 langgraph 投影假设覆盖 |
| 绑定图的 Turn.status/wait_reason/step_count | Runtime 的持久外部投影 | `DirectorRuntimeProjector` 校验 engine/state version、runtime_revision、终态；投影不是另一份可自行推进的 workflow |
| `DirectorTurn.revision` vs `runtime_revision` | 分别为 Turn CAS 与引擎投影水位 | 不能当同一版本比较或合并；图推进一次与 Turn 写一次不是必然一对一 |
| `RuntimeView` | 传输投影 DTO | 不是独立数据库状态机 |
| `DirectorGraphState.status/revision/step_count` | 绑定图的 checkpoint position | request/proposal/receipt/fact 的复制仅作重放线索；不能反写领域真相 |
| runtime control/lease/epoch/signal claims | 恢复与控制权威 | stop 与 resume fencing 必須保留；不能靠客户端按钮状态替代 |
| `DirectorInvocation` | 模型调用审计权威 | 每 step/attempt 稳定 key、request hash、冻结模型、submission、validated_output、usage；不是 workflow checkpoint |
| Proposal/items、应用事件、authorization | 意图/用户决定/委托事实 | create 不等于 apply；accept 不等于任意生产授权 |
| NodeRun / ProviderOperation / Artifact / Formal | 生产与正式资产事实 | checkpoint 和 Memory 只存引用/观察版本 |

模型依据：[assistant_models](../../backend/app/director/assistant_models.py)、
[turn_models](../../backend/app/director/turn_models.py)、[invocation_models](../../backend/app/director/invocation_models.py)、
[runtime models](../../backend/app/director/runtime/models.py)、[contracts](../../backend/app/contracts/director_runtime.py)。

## 4. 已证实的问题与不能夸大的问题

1. **命名超过行为**：权威文档中的“有界 Agent loop”此前把目标描述成现状；源码提供固定 structured call + workflow，需改正措辞，而不是删除稳定能力。
2. **tool 协议缺口**：请求有 tools，消息模型没有工具结果；响应未输出类型化 call。必须贯通 request/response/history/adapter，不是在 prompt 增加工具说明。
3. **缺统一 ToolRegistry/Executor**：runtime/domain_tools 是确定性 workflow domain port，包含 EXECUTE；不能整包交给 LLM。
4. **文本 orchestration 偏厚**：`text_transport.py` 同时编排 Turn、绑定、调用 journal、schema repair 和最终输出。可抽取公共调用执行，不另造日志、重试/模型选择系统。
5. **上下文职责并列而非重复**：`AssistantContextBuilder` 读 DB；`DirectorContextBuilder` 纯冻结。两者应组合，不按名字合并后失去测试 seam。
6. **manifest 两种形状不是两套独立配置**：catalog 的 `ModelCapabilityManifest` 被 `to_v3_model_manifest` 转换为消费侧 `ModelManifest`。转换与 compiler 一致性有债务，不能删桥后重造注册表。
7. **未来双写风险而非已证实数据损坏**：Turn 与 checkpoint 状态确有复制，已有 projector/fencing 防护。没有运行期数据库证据，不能断言现网已分叉。
8. **模型合同与 Provider 生命周期不同**：固定 seed 仍可标 active，而官方已公告退役。该差异和逐模型 compiler 风险见 [能力指南](MODEL_CAPABILITY_PROMPT_COMPILER.md)，不能靠自动 fallback 掩盖。

## 5. 保留 / 重构 / 移动 / 合并 / 删除映射

| 现有模块 | 处置 | 原因 |
|---|---|---|
| text_model.py、CapabilityTextModel | KEEP + 扩展 typed tool-turn 方法 | 已有精确模型/session-free seam，不重复建 registry |
| text_transport.py | REFACTOR，保持旧 structured façade | 将通用 invocation dispatch 复用于 Agent；保留 JSON repair 旧行为 |
| context_builder.py + assistant_context.py | KEEP / 组合 | 纯快照与有权限的 DB 聚合各司其职 |
| invocations.py / invocation_models.py | KEEP + 增补工具响应 schema | 唯一模型调用日志及未知提交边界 |
| runtime/langgraph_adapter、executor、checkpoint、control、wakeups、reconcile | KEEP | durable workflow 与 fencing 已存在；首阶段不物理改名 |
| runtime/domain_tools.py | KEEP 为 workflow port；选择性包装只读 service | submit_execution 不能进入首版 Agent tool catalog |
| turn_service / turn_models | KEEP + additive session linkage | 复用身份/CAS；Agent 与 workflow 必须明确不同 Turn kind |
| proposal_creation/service/commands | KEEP | 创建、partial apply、typed command 分工明确 |
| creative_capabilities / workflows | KEEP；局部 seam 整理 | Skill/Style/shot-language 已有真实编译，不建立第二套 packs |
| Provider registry/manifest/compiler/runtime/profile/identity | KEEP | 已有供应商隔离与不可变执行身份 |
| ProductionGraph/NodeRun/ProviderOperation/Artifact/Outbox | KEEP | 唯一生产主链，不重写 |
| 目录搬迁 | DEFER | 将 runtime 文档称 Workflow 即可；workflows 已被创作模板占用，不能简单覆盖 |
| 删除类/表/API/测试/迁移 | NONE | 本轮没有完成“无调用、无数据依赖、无兼容/发布依赖”的四重证明 |

## 6. Evidence Missing 与验证边界

- 未启动 API、Worker、数据库或付费模型；本轮不能给出账户可用性、真实 tool-selection 质量、端到端恢复或发布通过结论。
- 静态图帮助定位，注册/反射/跨进程调用以本地源码核对；未证明存在第二份业务真相的实际运行事故。
- LiteLLM 逻辑别名的真实上游由部署配置决定；仓库不证明当前在线账号、API 能力和路由版本。
- 既有测试可用作后续回归：`test_director_text_transport.py`、`test_director_context_builder.py`、`test_director_turn_service.py`、`test_langgraph_director_runtime.py`、`test_director_engine_routing.py`；它们的存在不是本轮执行通过。
- 当前审计覆盖此次 Director/Workflow/Production/Provider 接口，不宣称已审完仓库每个模块。
