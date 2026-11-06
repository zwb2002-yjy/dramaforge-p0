# DIRECTOR_RUNTIME — 导演编排 Runtime 权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）；
决策背景见 [adr/0007-director-runtime-langgraph.md](adr/0007-director-runtime-langgraph.md)。

Director Runtime 是**独立于生产执行的编排 runtime**：它驱动导演轮次、提案和
用户决策，但从不拥有媒体、NodeRun、Formal 或任何 Canonical 创作事实的写权。
生产执行见 [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md)。

## 核心概念

| 概念 | 含义 |
|---|---|
| DirectorThread | 用户对话容器（持久）。 |
| DirectorMessage | Thread 内的用户/系统消息。 |
| DirectorTurn | 一次**有界**导演任务/轮次；保留当前业务身份。 |
| DirectorInvocation | 单次文本模型调用身份：稳定 invocation_key、冻结模型身份、submission 状态、用量、成本与经验证响应。 |
| Proposal | 类型化 diff 提案（story / shot / editing 等），只能通过 typed command registry 应用；Assistant 永远 proposal-only。 |
| NextAction | 导演给出的下一步建议；不是自动执行。 |
| 用户决策 | 用户对 Proposal 的接受 / 部分接受 / 拒绝，持久化记录。 |
| Runtime signals | 用户决定与生产事实作为持久事件/Runtime wakeup 恢复；不再维护第二套 BusinessCheckpoints 协调器。 |

三种身份不得混淆：DirectorThread（对话容器）、DirectorTurn（轮次业务身份）、
`runtime_execution_id`（实现层检查点执行身份，与 Turn 及 engine_version 绑定）。

接受提案时先按 Project → Proposal → 目标行顺序加锁；目标行刷新后检查版本，
两个提案不能同时覆盖同一版本。引用命令校验 Asset 的项目以及待删除 Binding 的 Shot 归属。
`editing.repair_proposal` 是有界的需求确认：重验 EditSession 版本、时间线镜头及项目归属后，
只登记提案决议，不修改时间线或生产事实，不创建 NodeRun；实际 Repair 仍需独立用户确认。

## 引擎与检查点

- `DIRECTOR_RUNTIME_ENGINE` 只接受 `langgraph`；执行、重放和恢复没有第二种引擎。
- `langgraph` 需要 `DIRECTOR_CHECKPOINT_DATABASE_URL`（API 与 worker-director
  均接收，用于能力报告与实际执行），
  使用私有 `director_runtime_checkpoints` schema（迁移 `20260910_0066`，
  角色 `dramaforge_director_checkpoint`，对 `PUBLIC` / `dramaforge_app` REVOKE，
  不进应用 model registry）。
- checkpoint 未配置时，Story / Shot / Editing 的结构化文本入口与 Runtime start
  共用可用性门；在创建 Turn / Invocation 或调用文本模型之前拒绝，避免返回文本后才失败。
  MANUAL 媒体生产继续可用；配置存在不代表真实 checkpoint 连接已通过验收。
- 引擎身份按 Turn 全有或全无（`ck_director_turn_engine_binding`），
  `runtime_execution_id` 唯一。
- 代码位置：`backend/app/director/runtime`（engine ports、路由、投影、唤醒、
  LangGraph adapter）；`backend/app/director/turn_service.py` 保留查询/CAS/
  业务校验能力，但单一 Runtime adapter 负责流程推进。

## Worker、Inbox 与唤醒

- `worker-director`（`arq app.workers.director.WorkerSettings`）消费
  `dramaforge:director` 队列；Provider 调用被禁用。
- `director_inbox` / `director_wakeups`：跨进程丢失情况下保留原子回执/唤醒。
- `director_runtime_controls` / `director_runtime_wakeups` /
  `director_runtime_signal_claims`：控制 epoch、唤醒与信号认领，
  支撑 resume fencing。
- 导演 Worker 停止时，MANUAL 生产路径必须仍能完成全流程
  （空项目 → MP4/SRT）。

## 当前有界执行与 Agent Loop 目标

当前实现有文本调用和持久编排两种职责，不能将目标 Agent Loop 当成已实现事实：

- 文本任务由 `DirectorTextRuntimeAdapter.generate_structured` 执行固定 schema
  请求，必要时同一模型最多一次 schema 修复；调用身份和结果由 Invocation/Turn 持久化。
- `LangGraphDirectorRuntime` 执行固定的 propose → await_decision →
  submit_execution → await_execution → confirm_candidate 流程及拒绝/无需执行分支。
  其中 propose 的领域 port 读取已有 Proposal/经验证 suggestion，不调用 LLM 自主选工具。
- 当前 TextGenerateRequest 虽有 tools 字段，但消息/响应适配尚未构成完整的
  tool-call → ToolResult → LLM 闭环，因此不宣称已实现自主领域工具 Agent。

图的步数护栏、稳定命令键、租约、stop、resume fencing 和检查点继续保留。
生产执行只能消费已有用户决定及持久授权；图节点不能长期 sleep 或轮询等视频完成。
每次恢复通过领域 port 核实最新已提交事实，不能用 checkpoint 中的观察值反写业务真相。

目标是在现有模型调用/审计基础上增量增加 DramaForge-owned Agent Loop；
其只读工具上限、模型调用上限、可恢复工具错误及压缩策略是待实现合同，不是当前能力。
目标合同收拢在本文末尾，依赖顺序见
[ARCHITECTURE_MAPPING §5](ARCHITECTURE_MAPPING.md#director-agent-sequence)。

## 状态权威

| 数据 | 唯一权威 |
|---|---|
| 用户消息和决定 | Director domain 持久记录（模型上下文只是引用） |
| Proposal 内容及应用结果 | Proposal / 业务应用记录（检查点不拥有第二份可修改事实） |
| 当前流程位置 / interrupt | 被指定的 Runtime engine（DirectorTurn.status 是外部可读投影） |
| 控制 epoch、租约、stop 请求 | Director runtime 控制记录 |
| 已受理命令及关联执行 | 既有命令回执、NodeRun（检查点只保存 command_key/receipt 引用） |
| 生产结果与 Formal | 既有生产/资产事实（事件和导演缓存可滞后） |
| 文本调用结果 | Director invocation 审计记录（恢复时复用经校验结果） |

## 与 Production Runtime 的契约

- 业务命令：服务端持久化稳定 `command_key`（首次提交前持久化，与已批准动作
  及输入指纹绑定）、`expected_versions` 乐观并发、`plan_fingerprint` 冻结
  计划哈希、`authorization_ref` 持久授权引用；`origin` 只是关联数据。
- 返回统一 Receipt：同 key 同 payload 返回原回执；同 key 不同 payload 冲突；
  accepted 表示受理而非媒体完成。
- 生产命令入口拥有自己的事务，不接受导演事务对象；生产不反查导演数据库。
- 文本通道复用现有模型解析与 LiteLLM adapter（见
  [MODEL_PROVIDER.md](MODEL_PROVIDER.md)）。

## 恢复

- 可恢复轮次通过数据库函数/授权（迁移 20260908_0057–0060）跨进程重启恢复，
  复用经校验的 invocation 结果，不重复付费调用。
  文本模型解析冻结版本化 Proxy 部署引用；已 prepared 但尚无 Invocation 的旧请求
  要求显式重建和新请求键，不能重启后重新绑定模型。传输尝试次数与失败阶段持久化于
  Invocation 摘要，独立于业务 schema repair 次数。
    每次显式文本操作最多一个 primary Invocation 和一个同模型 schema-repair Invocation；
    第二次结构校验失败即终止，无第三次修复或规则回退。修复输入截断为 20,000 字符原输出
    和 4,000 字符错误说明。每个 Invocation 的 Proxy HTTP 默认各阶段超时为 120 秒，
    仅已证明发送前的连接失败最多重试一次；这不是总墙钟截止或额外上游调用授权。
    已可能发送的超时保留 `unknown_submission`，同请求键重入只读取原事实，不重发 primary
    或 repair。界面模型证据显示格式修复次数，详细尝试与失败阶段留在原 Invocation。
- 唤醒重放由 `wakeup_replay.py` 与 worker 启动恢复承担。
- Assistant 边界：Shot 建议为非持久响应；editing 建议持久化
  DirectorProposal/DirectorProposalItem 并只能经 typed command registry 应用。

## Proposal 创建与应用分工

`director/proposal_creation.py` 只统一 DirectorProposal 父子行的持久创建：
thread/project 归属、先父后子的 flush、输入项顺序、默认状态及 expected version。
Story、Editing suggestion / repair、已授权 delegation 共用此处；领域 payload 和
Story 的 `sort_order` 仍由 feature 构造，创建层不 commit、不执行 command。
delegation 的 applied/accepted 记录必须在原有显式授权校验之后创建。

这不是统一所有叫 Proposal 的实体：资产域 `ShotChangeProposal` 保留独立语义。
Apply 的部分成功、幂等持久 item identity、Save/Formal/Export 用户门均未迁入创建层。

## 实验提案与唯一分支

Director 的 experiment.create / shot.set_model_override 在用户 Apply
后调用与 HTTP 相同的 ExperimentBranch 创建服务，只创建 draft，不排队执行、
不改写 Shot 的 Formal 或模型绑定。每条命令明确一个 source_shot_id；旧单 Shot
payload 可规范化，含糊的多 Shot / 多模型覆盖拒绝，不静默选择一个。
Director 幂等键由持久 proposal-item 身份提供，不信任模型自选键；同一项重试复用
分支，不同项即使内容相同也可新建。HTTP 仍要求显式 idempotency_key。
相同键不同创建输入冲突，已开始/已决定的分支重放不重置状态。
Assistant context 只读取当前 Shot 的 ExperimentBranch，返回 experiment_id、
selected_model 与参数；后续 start / decision 仍通过现有显式用户 Gate。
ProductionExperiment / ShotExperiment 只保留历史存储，不再创建、采用或作为
Assistant 当前事实；旧 Phase 5 服务测试由当前分支回归测试替代。


<a id="director-agent-target"></a>
## Director Agent 工具循环合同（目标，未实现）

本节保留待实施设计，不授权启动新功能或付费验证。当前固定文本任务与 LangGraph
编排仍按上文运行。选择是在现有 Python / TextModelPort / Invocation 基础上增加自有
小型工具循环；LangGraph 继续拥有跨用户、跨 Worker 等待的流程位置，Production
继续拥有全部生产事实。不引入第二套模型注册表、调用日志、通用 Agent 平台或领域服务。
引擎选型决策及启用备选的条件仍由 [ADR 0007](adr/0007-director-runtime-langgraph.md) 管理。

### 现有实现定位

| 职责 | 现有入口及边界 |
|---|---|
| 固定结构化文本任务 | [text_transport.py](../backend/app/director/text_transport.py) 组合 Turn、模型解析、Invocation 与同模型 schema repair；保留原 generate_structured 行为 |
| 模型调用接口 | [text_model.py](../backend/app/director/text_model.py) 的 session-free TextModelPort；在同一接口增补 generate_turn，不另建 resolver |
| 上下文 | [assistant_context.py](../backend/app/director/assistant_context.py) 负责授权 DB 聚合，[context_builder.py](../backend/app/director/context_builder.py) 负责纯 JSON 冻结；二者组合而非互相替换 |
| 持久流程 | [langgraph_adapter.py](../backend/app/director/runtime/langgraph_adapter.py) 与 [domain_tools.py](../backend/app/director/runtime/domain_tools.py)；propose 读取已存提案，不能把含执行命令的 workflow ports 整包暴露给模型 |
| 事实读取与提案 | ProjectService、Scene/ShotWorkbenchService、AssetCardReadService、ModelInspectionService 和 proposal_creation；工具直接复用授权 service，不调用本机 API 或复制业务 SQL |

DirectorTurn.revision 是业务 CAS，runtime_revision 是引擎投影水位，不能合并比较。
checkpoint 中的 proposal、receipt、production fact 仅为观察和重放线索；恢复时重读领域
事实。Assistant 的 Shot suggestion 与持久 Proposal 不是同一对象。

### 模型与工具合同

以下类型均为目标合同；先扩展当前 LiteLLM 通道，不增加未经验证的厂商直连。

| 类型 | 必要内容 |
|---|---|
| AgentMessage / AgentToolCall | system/user/assistant/tool；assistant 的调用列表；tool 的 call_id、name、结构化结果；arguments 必须为 JSON object，不接受可执行代码 |
| AgentModelRequest | 有序消息、获准 ToolSpec、tool_choice、输出 schema、冻结模型解析、limits |
| AgentModelResponse | text、tool_calls、usage、stop_reason、白名单 metadata；文本和工具皆空判 malformed |
| AgentTurnResult | turn/thread、status、assistant_message_id、实际 proposal_ids、stop_reason、usage、version |
| ToolSpec | name/version、description、输入/输出 schema、risk/side_effect、requires_confirmation、timeout_ms、source、schema_hash、结果大小上限 |
| ToolContext | 服务端认证的 actor/workspace/project、turn/thread/UI scope、expected_versions、trace、cancel/deadline、只读 service factory；不交付 session 或凭据给模型 |
| ToolResult / ToolError | call_id、ok、data 或安全错误 code/message/recoverable/retry_class/details、observed_versions、provenance、truncated、result_hash |

ToolRegistry 返回按 scope 过滤的不可变 ToolSpec 集，并按 name/version 解析 handler。
ToolExecutor 统一校验 schema（extra=forbid）、权限、归属、版本、超时、幂等及审计。
模型能力元数据须区分 structured_json、tool_calling、tool_results、parallel_calls、上下文
上限与已验证证据；未知能力拒绝，不按模型名称猜。精确模型、连接/部署修订与 invocation
沿用 [MODEL_PROVIDER](MODEL_PROVIDER.md)，不能仅冻结可重新绑定的逻辑别名。

首版仅开放 READ 和无网络、无生产副作用的 ANALYZE；后续 PROPOSE 只能幂等创建
真实 typed Proposal，不能 Apply 或执行生产。MUTATE、EXECUTE、DESTRUCTIVE 不向模型
开放。工具描述、返回内容及 MCP annotations 均是不可信数据，不能提升权限或确认级别。

### 循环、恢复与状态所有权

1. 验证 thread/scope、request_key、UI context 和观察版本；同 key 同 payload 读取原
   Turn/回执，异 payload 冲突。冻结模型、工具集合版本与 context_hash，领取单 Turn lease。
2. 每次模型网络调用前持久记录 Invocation submission；工具先串行执行，每次重验权限
   和 expected versions。工具参数、响应和错误保留 call_id，成对追加 assistant/tool 消息。
3. 模型选择下一工具，runtime 仅校验与调度，不按用户关键词硬编码业务路径。
   ToolNotFound、ToolInputInvalid、ModelToolCallInvalid、ToolExecutionFailed/SHOT_NOT_FOUND
   作为安全且可恢复的 ToolResult 返回模型；权限拒绝不扩大 scope。ModelUnavailable 或
   malformed 响应不换模型，仅执行已允许的同模型修复；未知模型提交阻塞并查 journal。
4. 初始工程上限仍待校准：每 Turn 6 次模型请求、12 次工具调用、120 秒总时限；单工具
   默认 5 秒且受总 deadline 约束；schema repair 最多一次并计入模型请求数。同工具、
   规范化参数及观察版本连续重复 3 次即停止；参数纠正后的调用仍允许。
5. 工具去重绑定 turn_id + step + call_id + args_hash + tool_version；同 call_id 异参数冲突。
   READ 明确未执行或瞬时失败可有界重试；PROPOSE 超时先查 receipt。可能计费或
   unknown_submission 的模型请求不盲重发。网络期间不持有 DB 事务，工具用短事务。
6. stop 持久更新 epoch 后阻止新调用，不能撤销已提交网络操作，也不隐式取消既有授权
   Production/Workflow。ContextStale/RevisionConflict 要求重读并重新提案，不改批准计划。
7. 输出必须引用实际存在的 Proposal；达到 step/call/deadline 限制时返回已完成部分和原因。
   Agent 输出提案后结束推理；用户接受后，独立授权才交给新的 Workflow Turn，关联
   origin_agent_turn_id。Agent CAS 与 graph projector 不同时写同一 Turn。

数据演进归 [DATA_MODEL](DATA_MODEL.md#director-agent-data)，API/宿主选择归
[API](API.md#director-agent-api)。完成回答/提案用 completed；限额或不可恢复错误用
failed + stop_reason，用户 stop 用 cancelled，版本冲突用 stale；blocked 是结果/UI 分类，
不另增数据库状态。旧引擎身份、checkpoint、submission 与历史记录不补造、不改义。

### 上下文、Skill/Style 与可选外部工具

上下文分为版本化安全/工具合同、服务端验证的 UI scope、有来源及覆盖范围的历史摘要、
带 observed_versions 的实时领域读取。压缩保留当前请求、安全规则、scope/versions 与
未闭合 call/result 对；先确定性裁剪，LLM 摘要计入调用上限。未知提交不重算历史。
只保留业务所需 transcript、动作和结果摘要，不保存隐藏思维链；公开事件不含 Key、
Authorization、签名 URL、完整敏感 payload 或原始素材。

复用 Thread/Message、ProjectCreativeProfile 和可失效的 ThreadSummary，不引入向量库。
Formal、模型 Binding、生产状态实时读取，不由 Memory 认定。Skill 是方法，Style 是表达；
复用 CreativeSkillSpec/Stack、StylePack、ShotLanguageCompiler 与已有编译快照。
优先级仍为显式用户 > 已接受提案 > project override > pack default；未采纳推荐保持 pending。
人物一致性仍依赖参考素材、模型、冻结参数和审核，不能承诺开启 Skill 就能保证一致。

MCP 延后且不是首版阻塞项：受控 connect → tools/list → schema/大小/风险校验 →
带 server 身份的 namespace registry → tools/call → ToolResult。schema 变化生成新版本/hash，
不改变运行中 Turn 的工具定义。凭据在服务端，文件与网络均受限；外部工具不管理循环或
领域事实。不强制把内部服务 MCP 化，不开放 unrestricted shell/filesystem/browser control，
也不因厂商 hosted tool 或 readOnly 标注而继承执行权限。

### 验收边界

依赖顺序见 [ARCHITECTURE_MAPPING](ARCHITECTURE_MAPPING.md#director-agent-sequence)。
只读组合验收仍须分别证明：模型能按上下文选择不同工具顺序、实际调用授权 service、
错误带 call_id 回到模型、模型能改参/list 后纠正、step/call/deadline 均能终止、重启/stop/
租约/幂等成立、压缩不拆工具对、数据库前后无 Shot/Asset/Formal/NodeRun/ProviderOperation
写入（会话与审计允许）。每步模型身份、上下文 hash、工具版本、参数 hash、观察版本、
延迟、错误及 usage/cost_status 可追溯；未知费用不猜值。
Mock 只证明程序机制；真实模型工具选择质量须单独授权与验收，不继承历史付费许可。
各阶段退出时停止新受理、保留既有提案/审计/冻结 Workflow 的恢复，不删除历史数据。
