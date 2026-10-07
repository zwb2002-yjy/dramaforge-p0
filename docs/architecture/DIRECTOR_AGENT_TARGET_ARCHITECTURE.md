# Director Agent：目标架构与边界合同

Status: proposed-design，**未实现，不代表 Phase 1 已获启动**。本文细化
[ARCHITECTURE_MAPPING](../ARCHITECTURE_MAPPING.md) 中的待实施映射，服从
[架构宪法](../CANONICAL_ARCHITECTURE.md)、[模块边界](../MODULE_BOUNDARIES.md)、
[Director 权威](../DIRECTOR_RUNTIME.md) 与 [模型权威](../MODEL_PROVIDER.md)。
当前事实见 [现状审计](DIRECTOR_AGENT_CURRENT_STATE.md)，实现顺序见 [实施计划](DIRECTOR_AGENT_IMPLEMENTATION_PLAN.md)。

## 1. 架构决策

采用 **DramaForge-owned lightweight Agent Loop + 现有 TextModelPort 的增量扩展 + Internal Tool Registry + LangGraph durable workflow + 原 Production Runtime**。
不新增通用 Agent 平台，不引入 swarm/planner-executor 层级，不重新实现资产、模型目录、生产调度或审计系统。

```text
LLM owns decisions              （在获准工具集合内选择动作）
Agent Runtime owns reasoning loop
LangGraph owns workflow position
DramaForge owns domain truth
Production Runtime owns execution
```

LLM 的 decision 不等于权限、用户批准或事实；每次调用都经服务端校验。

| Runtime | 接受/返回 | 拥有 | 绝不拥有 |
|---|---|---|---|
| Director Agent | message + UI scope → answer/proposal/blocked | 模型→工具循环、短期上下文、步数/调用/时间护栏、工具错误反馈 | Formal、生产写权、隐式授权、跨天等待 |
| Director Workflow | 已存提案/用户决定/委托 → RuntimeView | checkpoint、interrupt/resume、等待用户/生产、fencing、恢复 | 动态自由推理、第二份 Proposal/NodeRun 真相 |
| Production | 类型化已授权命令 → receipt/事实/Artifact | Graph、NodeRun、ProviderOperation、媒体与血缘、Worker 执行 | 聊天历史、Agent Memory、自动替用户 Formal |

## 2. 完整目标调用链

```text
User + UI(project/scene/shot/selection)
 → Director API（认证、RLS、幂等受理）
 → DirectorAgentRuntime
 → AgentContextBuilder（复用 AssistantContextBuilder + DirectorContextBuilder）
 → AgentLoop
 → 现有 TextModelPort 的 generate_turn（新增类型化能力）
 → CapabilityTextModel / LiteLLM adapter / Gateway / LLM
 ← ModelResponse(text, tool_calls, usage, stop_reason)
 → ToolRegistry（暴露过滤后的 immutable ToolSpec 集）
 → ToolExecutor（scope、schema、risk、timeout、dedupe、日志）
 → Existing Application Service / 可选 MCPToolAdapter
 ← ToolResult / 可恢复 ToolError
 → tool-role message → LLM → … → Answer / ProposalRef
```

```text
Agent create_proposal（仅提案持久化）
 → 用户 Accept / Partial Apply（既有 ProposalService）
 → 如需生产：用户显式委托 + 持久 ProductionAuthorization
 → 独立 Workflow Turn（关联 origin_agent_turn_id，不复用推理状态机）
 → 现有 DirectorRuntimeStart/Delegation + LangGraph
 → Production command（command_key/expected_versions/plan_fingerprint）
 → NodeRun → Outbox → Worker → compiler → Provider → Artifact / Review
 → 事件 → Workflow Resume → 等用户确认 Formal
 → 用户明确要求后启动下一次有界 Agent Turn，解释结果
```

**接受创作 diff 不等于授权付费生产；生产完成不等于自动 Formal。**
Agent Turn 在输出提案后终结自己的推理；UI 可显示 awaiting_user，但等待由提案事实/Workflow 拥有。
首版不让同一 Turn 同时由 Agent CAS 与图 projector 写 status。

## 3. 模型接口：扩展 seam，不造第二个 registry

现有 [TextModelPort](../../backend/app/director/text_model.py) / CapabilityTextModel 保留，
旧 `generate(TextGenerateRequest) -> ProviderCreateResult` 行为不变。
在同一 seam 增加 `generate_turn(AgentModelRequest) -> AgentModelResponse`；“AgentModelPort”是此能力的类型投影，
不是独立模型 resolver、持久模型表或自动 fallback 层。

目标类型（放 `contracts/director_agent.py`，以下为未实现合同）：

| 类型 | 必要字段 |
|---|---|
| AgentMessage | role(system/user/assistant/tool)、content；assistant.tool_calls；tool.tool_call_id、tool_name、结构化结果 |
| AgentToolCall | id、name、arguments（解析后的 JSON object）、原始解析错误摘要；不接收可执行 Python/SQL |
| AgentModelRequest | ordered messages、允许的 ToolSpec、tool_choice、output schema、已冻结 model resolution、limits |
| AgentModelResponse | text、tool_calls[]、usage、stop_reason、provider_metadata（白名单）；内容/工具两者皆空为 malformed |
| AgentTurnResult | turn_id、thread_id、status、assistant_message_id、proposal_ids、stop_reason、usage summary、version |

Adapter 把 OpenAI-compatible `tool_calls`、Anthropic tool_use 或 Gemini function-call 等供应商形状转换到以上类型；
首阶段只改当前 LiteLLM 面，其他厂商不新增未经验证直连实现。不能把供应商 SDK 类型传入 loop。
`tools` 已存在不表示当前 upstream alias 支持；新增能力元数据至少区分 structured_json、tool_calling、tool_results、parallel_calls、上下文上限及 verified evidence。
未知能力 fail closed，不凭模型名字猜。

精确身份：复用 ModelBindingResolver、ModelRegistry、DirectorInvocation；记录 logical model、profile/version、gateway route identity（能获得时）、响应 reported model。
LiteLLM 的 alias 能由部署重新绑定，且已有路由 retry 配置；因此“冻结 logical alias”**不证明上游部署不可变**。
Phase 1 明确记录此缺口，Phase 2 上线前要求 route revision/attestation 或受控固定部署；不能新增静默模型切换。
不改网关凭据边界，不复活 workspace 文本 Key 表单。

## 4. Tool System

### 4.1 小接口、深实现

```text
AgentTool.spec() -> ToolSpec
AgentTool.execute(validated_input, ToolContext) -> ToolResult
ToolRegistry.describe(allowed_scope) -> tuple[ToolSpec, ...]
ToolRegistry.resolve(name, version) -> AgentTool
ToolExecutor.execute(call, context) -> ToolResult
```

`ToolSpec`：name、version、description、input_schema、output_schema、risk_level、side_effect、requires_confirmation、
timeout_ms、source(internal/mcp/external)、schema_hash、最大结果大小。
`ToolContext`：可信 actor/workspace/project、Turn/thread、current UI scope、expected_versions、trace_id、
cancellation/deadline、只读 service factory。actor/权限不从 LLM 参数读取；不把 DB session、凭据或授权 secret 交给模型。
`ToolResult`：call_id、ok、data、error、observed_versions、provenance_refs、truncated、result_hash；固定 schema。
`ToolError`：code、safe_message、recoverable、retry_class、可公开 details；不泄露 SQL、堆栈、secret、跨项目实体是否存在。

### 4.2 权限矩阵

| 级别 | 首版策略 | 示例 |
|---|---|---|
| READ | 允许，仍校验 RLS/归属/分页上限 | get_shot、get_model_capabilities |
| ANALYZE | 仅确定性、无外网、无生产副作用 | dry-run semantic compile、比较冻结参考 |
| PROPOSE | Phase 3 才开放；幂等写 Proposal 不是生产 truth | create_proposal |
| MUTATE | 不向首版 LLM 暴露 | 直接改 Shot/正式资产 |
| EXECUTE | 不向 LLM 暴露；用户 Gate 后 Workflow 才可提交 | generate_video、paid probe |
| DESTRUCTIVE | 禁止 | delete_asset、shell 文件删除 |

不能因 MCP annotations 声称 readOnly 就信任工具；服务端显式 allowlist 才有权。
Tool description/result 是不可信数据，不得提升 system 指令或确认级别。

### 4.3 第一批工具与现有 Service 映射

| 目标工具（尚未注册） | 复用实现/缺口 | 开放阶段 |
|---|---|---|
| get_project | [ProjectService.get_project_for_owner](../../backend/app/access/projects.py) | P2 |
| get_scene / list_shots | [SceneWorkspaceService.get_workspace](../../backend/app/workbench/scene_service.py) 的授权聚合；返回限量 DTO | P2 |
| get_shot | [ShotWorkbenchService.get_workbench](../../backend/app/workbench/scene_service.py) | P2 |
| get_asset / get_formal_asset | [AssetCardReadService.read_card](../../backend/app/assets/asset_card_service.py)，Formal 指向实时业务事实 | P2 |
| get_generation_snapshot | [WorkbenchExecutionService 的冻结计划读取](../../backend/app/production/workbench_execution.py) + [trace_query](../../backend/app/production/trace_query.py)；需新增有授权的统一只读 façade，不返回 secret/wire/raw URL | P2 |
| get_model_profile / get_model_capabilities | profile resolver + registry/manifest/catalog；输出 runtime subset、限制和 evidence，不从 prompt/记忆猜 | P2 |
| preview_generation_compile | build_plan + 纯编译 seam；不得调用 create_and_dispatch/prepare_media_submission | P2 后半 |
| get_style / get_active_skills | [AssistantContextBuilder](../../backend/app/director/assistant_context.py) 与 [creative_capabilities](../../backend/app/director/creative_capabilities/) 的现有快照和 registry | P5；前期随上下文提供 |
| create_proposal | [proposal_creation.create_proposal](../../backend/app/director/proposal_creation.py)，由 tool façade 做 typed draft/business validation | P3 |
| get_neighbor_shots / list_scenes / list_assets / get_character / list_characters / get_review_result | 在已有 workspace/asset/review read service 基础上按实际需求投影；无独立 service 的先提取共享 façade，不在 tools 内复制 SQL 业务规则 | 延后，不为列表完整而造接口 |

若现有读取只在 API helper 内，不从 Agent 调本机 HTTP，也不让 Agent 层依赖 api/v1。
将有价值的读取下沉至所属 application read service，API 与 tool 共同消费；严格限于确有消费者的 seam。

## 5. 生产级 Agent Loop 语义

1. 受理 message：验证 thread scope、request_key、权限、UI context；同 key 同 payload 返回同 Turn，同 key 异 payload 冲突。
2. 冻结模型身份/工具集合版本/上下文 hash；获取单 Turn lease。首版工具串行，避免引入并发写语义。
3. 调模型前检查 stop/deadline/model-call/token 限额；通过现有 InvocationService 在网络前记 submission。
4. 解析 response；工具参数必须 JSON object，schema `extra=forbid`，名称/version 必须已注册。invalid/unknown 作为可恢复工具结果回模型。
5. 每次工具调用前重验权限、scope、expected version；执行超时受总 deadline 约束。大结果分页/摘要，结果哈希和观察版本可审计。
6. 成对追加 assistant call 和 tool result；不能丢掉 call_id，不能把 tool result 伪装成 user 指令。随后由模型决定下一动作，不按用户关键词 if/else 选业务工具。
7. 最终 output 经 AgentTurnResult schema 校验；proposal 必须引用实际创建的 ID，不接受模型编造 ID。达到限制返回 bounded/blocked，不伪造成功。

### 护栏和恢复

- 初始工程默认（待测试校准）：每 Turn 最多 6 次模型请求、12 次工具调用、120 秒总时限；每工具 5 秒默认；schema 修复最多 1 次且计入请求上限。不是产品镜头数限制。
- 无进展：同工具/同规范化参数/同观察版本连续重复 3 次即 stop；改变参数后的正确调用仍允许。
- call 去重键：`turn_id + step + call_id + args_hash + tool_version`。同 call_id 异 args 为冲突；PROPOSE 再用 request idempotency 防止跨重放重复提案。
- READ 明确未执行/瞬时失败可有限重试；PROPOSE 超时先查询既有 receipt。模型请求 `unknown_submission` 先恢复 journal，不盲目重发可能计费请求。
- stop：持久 stop/epoch 后拒绝新调用；已发生网络提交不能被描述为“已撤销”。现有已授权 Production/Workflow 不随聊天 stop 被悄悄取消。
- 模型循环不持有 DB transaction 跨网络；工具短事务，commit 后按既有模式恢复 RLS。
- ContextStale/RevisionConflict：重新读取事实，可解释并重新提案；不得把新事实强行套入已批准计划。
- context overflow：保留 system/security、当前 scope/versions、未闭合 tool-call 对及用户当前请求；压缩旧已完成消息成有来源摘要。先用确定性裁剪，LLM 摘要须计入调用成本/上限；不能对未知提交重算一遍历史。
- 不保存隐藏思维链；保存动作、选择、结果摘要与最终解释足以审计。

## 6. 错误合同

| 错误 | 对 LLM/用户语义 | 自动动作 |
|---|---|---|
| ToolNotFound / ToolInputInvalid / ModelToolCallInvalid | 可修正名称/参数；返回 schema 提示 | 消耗步骤，回 LLM；不执行 |
| ToolExecutionFailed / SHOT_NOT_FOUND | 可恢复业务失败 | LLM 可 list_shots 后纠正 ID；无信息泄露 |
| ToolPermissionDenied | 作用域/权限拒绝 | 不自动扩大 scope；不降级绕过 |
| ToolTimeout | 结果未知性与 side_effect 一起分类 | READ 有界恢复；PROPOSE 查 receipt |
| ModelUnavailable / ModelMalformedResponse | 模型不可用/响应无法规范化 | 不静默换模型；仅明确允许的同模型 schema 修复 |
| ModelSubmissionUnknown | 可能已计费，journal 未确定 | 持久阻塞，查询恢复，不 blind retry |
| AgentStepLimitReached / AgentCallLimitReached / AgentDeadlineReached | 限额终止 | 返回已完成工作和未完成原因 |
| AgentCancelled | 用户 stop | 停止新动作，保留证据 |
| ContextStale / RevisionConflict | 当前事实不再匹配预期 | 重新读/重新提案，不能偷偷修改 approved plan |

## 7. 数据与状态设计

复用 `DirectorThread`、`DirectorMessage`、`DirectorTurn`、`DirectorInvocation`、Proposal。
未来若实施 Agent Loop，直接调整当前 Turn 合同：增加 thread_id、turn_kind（agent/workflow，
当前持久轮次只有 LangGraph；不保留旧引擎兼容）及
origin_agent_turn_id；Message 增加 nullable turn_id 与 ordinal/idempotency linkage。
新增一个 **工具调用明细** 表（建议 director_tool_calls）不是第二套 model invocation log：
存 turn/step/call_id、spec/hash、脱敏 args、result summary/hash、observed_versions、latency、status/error。
唯一键保证重放；RLS/project FK 与现有模式一致。模型 step 仍在 DirectorInvocation，工具明细不可替代它。

Agent counters/control 写所属 Agent Turn；Workflow position 写 checkpoint 并投影到自己的 Workflow Turn。
Agent 增量控制字段为 agent_control_epoch、agent_lease_token、agent_lease_expires_at、stop_requested_at，
历史轮次允许为空。模型调用数由 Invocation journal计数、工具调用数由tool明细计数；持久计数缓存只能同事务更新。
Agent 的lease/control不复用要求graph runtime_execution_id的控制记录，避免伪造LangGraph绑定。
已完成回答/提案使用Turn.status=completed；限额或不可恢复错误用failed并保存stop_reason；
用户stop用cancelled，版本冲突用stale。blocked是结果/UI分类而非新增数据库status，保留现有CHECK。
不要给 DirectorTurn.status、LangGraph、RuntimeView 同时赋“独立权威”。
历史引擎绑定、checkpoint schema、submission state 不迁改，不删除历史列/表。
未来实现时直接调整当前未发布合同与调用方；只保留一套新执行路径，数据另行保管。

## 8. Context、Memory、Skills、Style

| 类别 | 来源 | 权威/过期规则 |
|---|---|---|
| Always-on | 安全规则、工具合同、当前模式 | 小而固定；版本化 |
| UI context | 已认证 project/scene/shot/selection | 服务端验证归属，不让 Agent 重新遍历寻找当前镜头 |
| Retrieved | ThreadSummary、近期消息、创作决策 | 非领域真相；标来源、覆盖范围与更新时间 |
| Tool-fetched | Shot/Asset/Model/Formal/Review/NodeRun | 实时领域读；返回 observed_versions |

Conversation History 用现有 Thread/Message；Working Memory 是本 Turn 的消息/工具观察；
Long-term Memory 首版仅新增可失效的 ThreadSummary，复用 ProjectCreativeProfile。
CreativeDecision 优先用既有 accepted proposal/decision 事实；没有独立生命周期前不建新表。
不引入 Vector DB。正式角色素材、model binding、Formal、生产状态永远实时读取，不能放进摘要当事实。

复用 CreativeSkillSpec/CreativeSkillStack、StylePackSpec、ShotLanguageCompiler、CreativeCapabilityCompiler：
Skill 表示“分析/规划方法”，Style 表示视觉/叙事表达；不是同一枚 UI 标签。
上下文注入版本化 guidance；生产 Prompt 只消费已接受/已保存的 compiled snapshot，
优先级仍是 explicit user > accepted proposal > project override > pack default。
Skills/Style 版本与哈希进入 provenance；未采纳的模板建议仅标 pending。
人物一致性必须解释 formal reference、顺序、视角覆盖、模型能力、prompt、generation snapshot、review/repair，
不得承诺“启用 Skill 就不漂”。

## 9. MCP 与通用工具

MCP 是外部工具协议，**不管理 Agent loop 或领域 truth**。
Phase 6 才新增 MCPClientManager/ServerConfig/Discovery/MCPToolAdapter。
流程：受控连接 → tools/list → schema/大小/风险验证 → namespaced registry → tools/call → ToolResult。
注册键必须含 server 身份；动态 schema 变更生成新 version/hash，运行中 Turn 不悄悄换定义。
凭据服务端保存；用户文件路径/网络出站/结果内容都要隔离，工具内容视为不可信。

| 通用能力来源/用途 | 结论 |
|---|---|
| 内部领域 read + proposal | 需要；直接 service adapter，不强制 MCP 化 |
| SDK function-tool schema/error normalization | 可借鉴合同，不为了通用工具引入第二个 runtime |
| 网页搜索/素材库/Drive/Blender/Unreal/OpenCut | 未来可扩展；每服务独立权限和审核 |
| MCP filesystem 限目录只读 | 暂不需要；先证明素材流程无法用现有 Asset service 完成 |
| unrestricted bash/write/edit/delete/browser control | 首版禁止；不经 Domain Model 写项目文件 |
| OpenAI hosted tool / Anthropic 原生工具 | 不直接等同内部权限；仅在专门 adapter 与明确模型合同下评估 |

## 10. API 与前端

保留现有 project-scoped routes，不先重做 UI。目标新增（均未实现）：

| API（/api/v1 前缀） | 合同 |
|---|---|
| POST /projects/{project_id}/director/threads/{thread_id}/messages | content、request_key、UI context、已观察领域版本；actor 来自认证。首版同步返回 AgentTurnResult + message_id/turn_id；同key重试只读回执 |
| GET /projects/{project_id}/director/threads/{thread_id} | 分页 messages、summary ref、关联 Turn；不能返回凭据/原始 tool 大结果 |
| GET /projects/{project_id}/director/turns/{turn_id} | 增量扩展既有 read，展示 assistant_message/tool_activity/proposal/awaiting_user/completed/failed |
| POST /projects/{project_id}/director/turns/{turn_id}/stop | 复用既有语义并按 turn_kind 路由，expected_revision + request_key |

复用 [events/sse.py](../../backend/app/events/sse.py) 的事件面而非新增 WebSocket 状态源；
首版可先 HTTP 查询 + activity events，token streaming 非上线 blocker。
每事件包含 event_id/turn_id/sequence/type/version，断线重连后 GET 为权威；前端不推导执行许可。

执行宿主选择：现有 API 路径允许文本调用，但 worker-director 明确无 Provider 权限。
首版有界 Agent 在 API-owned handler 执行，受持久 journal/stop 控制，不把队列延迟当 durability。
首版确定采用同步 POST + GET/stop 并发控制。202 后台受理不属于首版合同；
将来确需采用时须单独设计受控 text-only 执行宿主/可靠 outbox，**不能把内存 background task 宣称为 crash-safe 执行**。
禁止简单把 Key 注入现有 worker-director 来“修好”Agent。

## 11. Observability

复用 DirectorInvocation，关联 turn/thread/step、context_hash、logical model/binding/route revision、
工具 spec version、args hash、结果摘要、latency/error、token usage/cost_status、proposal refs、stop reason。
成本未知必须明确 unknown，不猜价格/不把 local query 当 paid readiness。
raw prompt、完整敏感 payload、signed reference URL、API key、Authorization header、凭据明文不进入公共事件/工具结果。
服务端只保存业务需要且受 RLS/保留期约束的 transcript；Provider 大结果与媒体仍用 Artifact 引用。

## 12. SDK 选型：针对当前仓库的取舍

官方材料核查日期：2026-09-24；以下是设计判断，不是跨 SDK 性能实测。

| 方案 | tool/MCP/memory/durability/HITL | 锁定、Python、调试与迁移代价 | 结论 |
|---|---|---|---|
| A LangGraph 全 Agent | 可构建工具图、checkpoint、interrupt；并非“不支持 Agent” | Python 现成，但把短循环也塞图会叠加现有 Turn/invocation 状态；必须额外防 replay 副作用 | 保留长流程；不用于首版短推理循环 |
| B Claude Agent SDK | 自带 agent loop、工具与会话，支持 MCP；权限/审核能力仍需领域封装 | Python/TS 入口，面向 Claude/Claude Code 执行模型；与现有 LiteLLM/journal 的职责重叠 | 不作为核心 Runtime |
| C OpenAI Agents SDK | function tools、MCP、sessions/tracing、HITL；不能据此推定完整生产 durability | Python，支持自定义模型/非 OpenAI provider，并非绝对厂商锁定；仍需适配现有 invocation、scope、workflow | 可借鉴，不引入平行执行状态 |
| D OpenClaw | gateway/session/tools/channels 平台，长会话恢复依赖其运行时合同 | 现有项目以 TS gateway 为核心；为 Python 领域服务再部署整个平台扩大安全/运维面 | 不采用；其恢复一致性未在本项目验收 |
| E pi Agent Runtime | TS agent-core 的 model/tool loop、context transform、事件与取消 | 需 TS sidecar/跨语言桥；现有 Python service 无法直接复用 transaction/RLS。不能宣称等价 LangGraph durability | 借鉴简洁 loop，不引入运行时 |
| F DramaForge-owned | 自有小循环/ToolRegistry；MCP 后接；历史复用现有模型，durability 交给既有 workflow | Python原栈；新增代码集中在本项目缺口，保留已有审计、生产集成，ModelPort 可替换 | 选用；必须完成错误/取消/重放验收，不能只写 demo while |

来源（以实际官方页面为依据，不复制长段正文）：

- LangGraph [durable execution](https://docs.langchain.com/oss/python/langgraph/persistence)、[interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。checkpoint 重放仍要求幂等副作用；移除它就要自建持久位置、暂停/恢复、版本兼容、并发 fencing，当前没有收益证明。
- Claude [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)。
- OpenAI [Agents SDK guide](https://developers.openai.com/api/docs/guides/agents/sdk)、[SDK upstream](https://github.com/openai/openai-agents-python)。
- OpenClaw [官方仓库](https://github.com/openclaw/openclaw)。
- pi [agent-core README](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)。
- MCP [Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)。

## 13. 目录：先新增缺口，不大规模 rename

```text
backend/app/contracts/director_agent.py       # 新：纯模型/工具/结果合同
backend/app/director/agent/
  runtime.py                                  # 新：轮次协调，后续阶段
  loop.py                                     # 新：有界模型—工具循环
  context.py                                  # 新：组合现有 reader + snapshot
  tools/{base,registry,executor,reads,model,proposal}.py
  memory/summary.py                           # P5 才新增
  tools/mcp/{client,adapter}.py                # P6 才新增
backend/app/director/text_model.py             # 扩展既有 port
backend/app/director/text_transport.py          # 保留 façade，抽公共 dispatch
backend/app/director/invocations.py            # 唯一模型调用 journal
backend/app/director/runtime/                   # 保留物理路径，语义明确为 Workflow
backend/app/director/creative_capabilities/     # 复用 Skill/Style/Compiler
backend/app/production/ + execution/ + providers/ # 不复制
```

候选抽取的文件须在实施时结合局部规模决定；不为每个名词建一层 wrapper。
本轮只输出文档；未建上述 Python 模块、API、数据迁移或部署服务。
