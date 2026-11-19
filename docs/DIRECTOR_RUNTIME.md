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
- 该队列同时承载已受理 Agent Turn：`dispatch_director_wakeups` 每 5 秒按游标扫描
  `turn_kind='agent' AND status='queued'` 并入队 `execute_agent_turn`；数据库行是
  唤醒权威，队列条目只是加速。
- `director_inbox` / `director_wakeups`：跨进程丢失情况下保留原子回执/唤醒。
- `director_runtime_controls` / `director_runtime_wakeups` /
  `director_runtime_signal_claims`：控制 epoch、唤醒与信号认领，
  支撑 resume fencing。
- 导演 Worker 停止时，MANUAL 生产路径必须仍能完成全流程
  （空项目 → MP4/SRT）。

## 当前有界执行与 Agent Loop

当前实现保留结构化文本与 Workflow，并增加由 HTTP 202 受理、Director Worker 领取的
有界 Agent：

- 文本任务由 `DirectorTextRuntimeAdapter.generate_structured` 执行固定 schema
  请求，必要时同一模型最多一次 schema 修复；调用身份和结果由 Invocation/Turn 持久化。
- `LangGraphDirectorRuntime` 执行固定的 propose → await_decision →
  submit_execution → await_execution → confirm_candidate 流程及拒绝/无需执行分支。
  其中 propose 的领域 port 读取已有 Proposal/经验证 suggestion，不调用 LLM 自主选工具。
- `agent_harness.py` 使用同一 LangGraph 引擎实现 model → tools → model，
  `agent_service.py` 复用 Turn/Message/Invocation，独立 Agent lease 与工具审计。
  目前开放项目、场景、镜头、资产七个 READ 工具、媒体能力检查/纯编译预览
  两个只读模型工具与 `shot_prompt_propose`；后者
  只创建一个镜头的一个 image/video prompt 待采纳提案，返回真实 Proposal 后停止。
  Apply、媒体生成、Formal 和 Export 继续由已有用户入口控制。
- 文本协议支持 assistant tool_calls / tool result / call_id、usage 与 stop_reason；
  新 Agent 要求显式选择 `chat_tools_v1` 连接，旧 `chat_text_v1` 不自动升级。
  合同和 mock 验证不表示真实模型工具选择质量已验收。

### Agent 受理、领取与 fencing

- HTTP 受理（`DirectorAgentService.accept`）在**一个短事务**内写入 user Message、
  `status=queued` 的 Turn（含冻结的 intent/工具/技能/上下文快照、request hash、
  `accepted_revision`）与 `director.turn.accepted` Outbox 事件；不打开 checkpoint、
  不调用模型、不留内存后台任务。断开 HTTP 不会撤销已受理工作。
- 同 request_key 同规范化输入返回原受理事实（HTTP 200，原事实不随完成改写）；
  同键异输入 409。GET requests 返回该受理与当前 Turn 摘要，不依赖当前模型/默认参数重算。
- Worker 扫描（`app.pending_agent_director_turns`）是唤醒的恢复路径：Redis 任务或
  Outbox 发布丢失时，只要 Turn 仍为 `queued` 就会被下一次扫描重新发现。
- 领取是单条 compare-and-set：`queued → thinking`，`agent_control_epoch+1`，
  写入本 worker 的 `agent_lease_token`/`agent_lease_expires_at` 并 `revision+1`。
  第二个 worker 只会读到 `thinking` 或终态，不会加入执行；不存在同步与异步双重执行所有者。
- 执行前持久化 Invocation，网络期间释放应用事务。`thinking` 轮次**从不续跑**：
  lease 过期或进程重启时，恢复把在途文本收敛为 `unknown_submission` 并终止轮次；
  迟到结果因 lease/epoch 不匹配被拒绝，不能覆盖新 epoch 或复活终态。
- checkpoint 只保存图状态与审计 transcript；恢复读取的是持久领域事实，不用
  checkpoint 中的观察值反写业务真相，也不以 checkpoint 重放外部副作用。


图的步数护栏、稳定命令键、租约、stop、resume fencing 和检查点继续保留。
生产执行只能消费已有用户决定及持久授权；图节点不能长期 sleep 或轮询等视频完成。
每次恢复通过领域 port 核实最新已提交事实，不能用 checkpoint 中的观察值反写业务真相。

Agent 默认上限为 6 次模型调用、12 次工具调用、120 秒；可以请求更低上限。
同工具/参数/观察版本连续三次重复终止。工具参数错误返回模型纠正；版本变化停止为 stale。
调用前持久化 Invocation，网络期间释放应用事务；同 request_key 只读取原受理，
过期或重启遗留提交保留 unknown_submission，不重放模型请求。stop 不能撤销在途调用。
stop 同事务保存未完成工具的取消回执，并把在途文本标为结果未知；迟到文本可以补全
原 Invocation，迟到工具只补摘要，均不能复活轮次。终态读取也收敛遗留未完成记录。
Skill 上下文复用 CreativeSkillSpec/Compiler，冻结 profile/version/hash；不赋予执行权限。
实际模型上下文另读取 ProjectCreativeProfile 的全部已保存选择，以及当前 Scene/Shot
各自已保存的 creative_capabilities；保留来源对象、版本、compiled_hash 和 value_sources。
不把多个 Style 偷换成一个，也不把记录中的 pack 默认值提升成已接受提案；pending 推荐
不作为已采用事实。上下文源版本参与轮次守卫，即使未调用 READ 工具，期间修改已保存
场景也会使轮次 stale。没有保存快照时明确缺失，不从最新库默认值回填。
上下文预算覆盖 messages + tools 的 UTF-8 JSON 字节。仅按完整历史轮次从旧到新省略，
数据库历史窗口也按完整 completed Agent Turn 选择，以 Turn 时间/ID 和 Message ordinal
稳定排序；窗口省略、旧消息省略及不完整组排除分别可见，不在预算器之前悄悄截消息。
省略说明本身计入预算；系统约束、当前请求、工具定义和当前轮 call/result 不截断。
checkpoint 保留完整审计 transcript，Invocation 保存实际发送投影及 hash/字节/省略数量。
当前所需上下文超限明确停止。每次模型调用重验冻结的文本连接/模型修订，不静默换模型。
ToolCall 校验 name/version/schema/args 完整身份，重复读取原回执；中断不重放，晚到结果
只增加摘要，不覆盖已确认取消或失败。参数审计脱敏，公开活动只有 hash、版本、状态、耗时。
Agent 提案通过专用的读取/Apply HTTP 接线进入现有 ProposalService；Apply 仍为显式用户
操作，重复采用不二次改写，目标版本已变则拒绝覆盖，不创建 NodeRun 或 ProviderOperation。
更多类型提案、自动 Workflow 交接、ThreadSummary 与 MCP
仍按后续合同扩展，不因基础循环接通而宣称全部完成。依赖顺序见
[ARCHITECTURE_MAPPING §5](ARCHITECTURE_MAPPING.md#director-agent-sequence)。

## 状态权威

| 数据 | 唯一权威 |
|---|---|
| 用户消息和决定 | Director domain 持久记录（模型上下文只是引用） |
| Proposal 内容及应用结果 | Proposal / 业务应用记录（检查点不拥有第二份可修改事实） |
| 当前流程位置 / interrupt | 被指定的 Runtime engine（DirectorTurn.status 是外部可读投影） |
| 控制 epoch、租约、stop 请求 | 当前绑定图使用runtime控制记录；旧Agent使用Turn agent字段；O6统一目标见机构合同，不能误报已单存储 |
| 已受理命令及关联执行 | 既有命令回执、NodeRun（检查点只保存 command_key/receipt 引用） |
| 生产结果与 Formal | 既有生产/资产事实（事件和导演缓存可滞后） |
| 文本调用结果 | Director invocation 审计记录（恢复时复用经校验结果） |

## 与 Production Runtime 的契约

- 业务命令：服务端持久化稳定 `command_key`（首次提交前持久化，与已批准动作
  及输入指纹绑定）、`expected_versions` 乐观并发、`plan_fingerprint` 冻结
  计划哈希、`authorization_ref` 持久授权引用；`origin` 只是关联数据。
- 返回统一 Receipt：同 key 同 payload 返回原回执；同 key 不同 payload 冲突；
  accepted 表示受理而非媒体完成。
- 当前ProductionCommands由调用方提交事务；现有DirectorDomainRuntimeTools用独立session受理。
  生产不反查Director数据库、不接受LangGraph状态；机构原子准入的事务装配见下方D3目标合同。
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
## Director Agent 工具循环扩展合同（部分已实现，完整目标未完成）

本节说明现有工具循环及待实施扩展，不授权启动新功能或付费验证；当前实现范围以上文
及本节的明确标注为准，不代表完整目标已验收。固定文本任务与 LangGraph 编排继续运行；
自有小型工具循环基于现有 Python / TextModelPort / Invocation。LangGraph 继续拥有
跨用户、跨 Worker 等待的流程位置，Production
继续拥有全部生产事实。不引入第二套模型注册表、调用日志、通用 Agent 平台或领域服务。
引擎选型决策及启用备选的条件仍由 [ADR 0007](adr/0007-director-runtime-langgraph.md) 管理。

### 现有实现定位

| 职责 | 现有入口及边界 |
|---|---|
| 固定结构化文本任务 | [text_transport.py](../backend/app/director/text_transport.py) 组合 Turn、模型解析、Invocation 与同模型 schema repair；保留原 generate_structured 行为 |
| 模型调用接口 | [text_model.py](../backend/app/director/text_model.py) 的 session-free TextModelPort；在同一接口增补 generate_turn，不另建 resolver |
| 上下文 | [text_transport.py](../backend/app/director/text_transport.py) 调用 [context_builder.py](../backend/app/director/context_builder.py) 冻结本轮事实；thread 运行时在 [runtime/start.py](../backend/app/director/runtime/start.py) 组装提案快照 |
| 持久流程 | [langgraph_adapter.py](../backend/app/director/runtime/langgraph_adapter.py) 与 [domain_tools.py](../backend/app/director/runtime/domain_tools.py)；propose 读取已存提案，不能把含执行命令的 workflow ports 整包暴露给模型 |
| 事实读取与提案 | ProjectService、Scene/ShotWorkbenchService、AssetCardReadService、ModelInspectionService 和 proposal_creation；工具直接复用授权 service，不调用本机 API 或复制业务 SQL |

DirectorTurn.revision 是业务 CAS，runtime_revision 是引擎投影水位，不能合并比较。
checkpoint 中的 proposal、receipt、production fact 仅为观察和重放线索；恢复时重读领域
事实。Assistant 的 Shot suggestion 与持久 Proposal 不是同一对象。

### 模型与工具合同

以下为完整目标合同；当前已实现消息/响应、只读工具、媒体模型工具与受限提案合同，
其余扩展不能据本表当作已实现。继续使用 LiteLLM 通道，不增加厂商直连。

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

当前开放 READ 和受限的 shot_prompt_propose；后续 ANALYZE 不得有生产副作用，
PROPOSE 只能幂等创建真实 typed Proposal，不能 Apply 或执行生产。MUTATE、EXECUTE、DESTRUCTIVE 不向模型
开放。工具描述、返回内容及 MCP annotations 均是不可信数据，不能提升权限或确认级别。

### 循环、恢复与状态所有权

1. 验证 thread/scope、request_key、UI context 和观察版本；同 key 同 payload 读取原
   Turn/回执，异 payload 冲突。冻结模型、工具集合版本与 context_hash，领取单 Turn lease。
2. 每次模型网络调用前持久记录 Invocation submission；工具先串行执行，每次重验权限
   和 expected versions。工具参数、响应和错误保留 call_id，成对追加 assistant/tool 消息。
3. 模型选择下一工具，runtime 仅校验与调度，不按用户关键词硬编码业务路径。
   ToolNotFound、ToolInputInvalid、ModelToolCallInvalid、ToolExecutionFailed/SHOT_NOT_FOUND
   作为安全且可恢复的 ToolResult 返回模型；ToolPermissionDenied 保留拒绝回执并立即以
   permission_denied 终止，不再请求模型或执行同批后续工具，不能通过改参扩大 scope。ModelUnavailable 或
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

<a id="institution-runtime"></a>
## 机构统一执行目标合同（D3设计审查通过，未实施）

依据O1–O7、D1产品和D2数据设计。当前实现仍是上述有界Agent与固定流程；
新增MasterRun/BusinessFlow不是另一套Agent或Production Runtime。
本节完成状态/锁序/恢复/组件交叉审查；D4–D7继续细化领域与API并在D8全量冻结，不提前实施。

### 事实与控制归属

| 事实 | 唯一写者/数据 | 引擎能做什么 |
|---|---|---|
| 持续目标与当前计划 | MasterRun service、不可变Plan、typed Proposal决定 | 提出计划、等待；不得自批准或用回答代替目标完成 |
| 轮次/消息/文本调用 | Turn/Message/Invocation原服务 | 有界推理、原调用证据及停止；不重提未知提交 |
| 业务步骤/尝试 | BusinessFlow service三表 | 按注册定义推进并投影已有回执，不拥有媒体成功状态 |
| 引擎位置/checkpoint | 唯一LangGraph，Turn绑定的版本与execution ID | 恢复控制位置；观察数据不是正式写入权 |
| 执行控制 | RuntimeControl接口及绑定的唯一存储adapter | claim/heartbeat/fence/settle，不双写两处lease |
| 媒体事实 | Production Commands/Runtime，NodeRun/Operation/Artifact | 只通过授权端口提交或查询单回执 |
| 研究/知识/资产/正式选择/剪辑 | 各领域服务、现有用户门 | 使用注册读/提案/已决定命令工具，不能直接写ORM替代领域校验 |

ResearchAnalysis是结果覆盖清单，KnowledgeRevision是发布内容，PublicAssetPublication是共享资格；
三者不具有自己的Worker队列/lease/checkpoint，不形成第三Runtime。
私有资料本地提取继续由既有dispatcher有界处理，语义研究通过受控Turn/BusinessFlow；
技能只提供规则与输入输出约束，不获得独立授权。

### I6a-01已实施：BusinessFlow 持久化与服务

- 三表：`director_business_flow_instances` / `_steps` / `_step_attempts`（迁移 0107），
  项目FORCE RLS、运行角色只SELECT/INSERT/UPDATE；复合候选键拒绝跨项目伪造；
  `director_turns.business_flow_step_attempt_id` 以延迟FK绑定原Attempt。
- 定义是代码注册项（`business_flows.py`）：key/version/contract_hash、step_specs、
  completion_rule_ids、resume_rule_id、graph_entrypoint；同版本异合同拒绝注册，
  循环依赖/未知完成规则/未注册工具在创建时拒绝。内置 `shot_prompt_review@1`。
- 服务：`create_from_plan` 按计划flows创建冻结实例与步骤（幂等于run+plan+flow_key）；
  `apply_dispositions` 要求覆盖全部旧非终态实例，retain 只接受定义与输入hash均未变的实例，
  supersede/cancel 保留成功步骤；`advance` 按依赖计算ready、准备attempt后**在会话外并发**
  执行受控工具、再顺序记录回执；`progress`/`completion` 只读原Flow/Step/Attempt事实；
  `cancel_run` 取消未完成步骤并保留成功事实。
- 槽位：`(step_id)` 部分唯一索引覆盖活动状态与 `unresolved_external`；unknown_submission
  必有 unresolved_external，取消但远端未决仍占槽，不自动重发。
- 计划接线：`MasterRunService.apply_plan` 在同一事务写指针、处置旧实例并创建新实例；
  `control(verify)` 用注册完成规则给出 satisfied/checks；`control(cancel)` 取消未完成流程；
  `summary` 返回真实计数。生产/修复类动作只登记为 `waiting_execution`，不在此批次提交
  Provider Create（授权受理端口属 I6b）。
- 边界（不冒称）：本批次没有新增Worker驱动循环；`advance` 由调用方（后续 I6b 的
  Worker/受理端口）驱动，测试用注入执行器验证真实步骤链。读投影HTTP仍属D7设计未实施。

### I6a-02已实施：Worker 驱动与受控工具执行

- 迁移 0108 只新增 `app.pending_business_flow_contexts(limit, after, instance_id)`：
  返回仍有 `pending/ready/running` 步骤的非终态实例（或按 id 解析单实例作用域）的
  owner/workspace/project；SECURITY DEFINER 归 `dramaforge_worker_resolver`，仅
  `dramaforge`/`dramaforge_app` 可执行。
- `worker-director` 新增 `execute_business_flow` 作业与 `dispatch_business_flows` cron
  （每 10 秒、游标分页、稳定 job id）。实例行是唤醒权威：Redis 任务丢失后下一次扫描
  重新发现；没有新增队列或循环。
- `app/director/business_flow_worker.py`：解析持久项目作用域→设 RLS→加载实例→
  `BusinessFlowService.advance`。执行器 `ToolFlowActionExecutor` 只调用既有
  `ToolExecutor`/`ToolRegistry` 白名单；动作没有 Director Turn，attempt 是审计身份，
  `created_by_turn_id` 的 Thread 在存在时保留，工具错误转成有界 `FlowActionError`。
- 恢复：`advance` 开始前把 `running` 超过 300 秒的 attempt 以 `FLOW_ATTEMPT_STALE`
  终止，步骤同事务失败；**不重放**可能已提交提案的动作。生产/修复动作仍只登记
  `waiting_execution`，Provider Create 属 I6b 的授权受理端口。



### RuntimeControl接口与O6切换

Scope={project_id,workspace_id,actor_id}从可信鉴权或DB归属发现获取；Lease包含turn_id、
runtime_execution_id、worker_id、epoch、expires_at。方法包括bind、claim、heartbeat、check、
claim_signal、settle、request_stop、mark_project_stale，全部拒绝任意客户端claim。

P2a/I2a先统一接口：旧Agent同样已有runtime_execution_id，不能据其有无选adapter。
已冻结state_schema_version=director-agent-v1的Agent使用AgentTurnAdapter写旧lease；
现有director-runtime-state-v1固定图使用ControlTableAdapter；新director-agent-v2及director-runtime-state-v2
使用带epoch checkpoint隔离的ControlTableAdapter。旧v1不得被当作v2读取。
精确engine_version还须命中相应版本注册表。选择来自已持久化版本绑定，不在失败时自动切adapter。
有不完整/相互矛盾的引擎字段则拒绝，不同时写两套lease。D2不新增第三张租约表。

I3外发/授权通过后I2b才接纳新的Worker Agent Turn，冻结精确engine/state schema/runtime_execution_id，
以ControlTableAdapter写控制。旧Turn不静默改引擎或拷checkpoint到新格式；继续原身份核对结果，
不支持恢复的旧状态明确stale，必要的新目标动作须重新确认，不重发可能计费的原调用。
stop/late/restart回归和旧路径排空后，再评估删旧Turn lease；“考虑删除”不是必删或提前删。

新执行生命周期：短事务claim→提交→锁外图步骤/网络→独立短事务heartbeat→每次写入/发送前重验
Run epoch、当前计划new/retain资格、权限、版本及外发许可→短事务settle/CAS。
lease使用DB时间。D8核对源码：control.claim默认45s、上限300s，executor实际传300s；当前没有目标异步heartbeat循环。
新v2工程默认TTL=300s、heartbeat=30s；配置名director_runtime_lease_seconds（45..300）及
director_runtime_heartbeat_seconds（5..60且<=TTL/3），非法组合启动失败。数值是设计默认，不是已验设备SLA。
heartbeat用独立短事务，仅CAS当前Control owner/epoch/active资格，不反向持Control锁再取Project/Run锁；
每次新写/发送仍按完整锁序验证Run epoch与权限。续租不延长Turn/Run deadline或重置限额。
heartbeat/DB失联后禁止新副作用，已有响应按原调用身份保留待落库；不可凭客户端时间或“上次还活着”继续发送。
I2b用真实PG时间与故障屏障验证续租、超时接管、旧epoch迟到写；I0/I10再校准设备指标，不以改大TTL掩盖失控长事务。
Run暂停/取消/换计划提高epoch，过期执行者只能补原Invocation/Operation证据，不能推进正式状态。

### 当前源码揭示的事务缺口

I2a-02已实施：删除跨步持锁的`control.guard`，改为
`begin_step(lease)→StepTicket(epoch,revision)`（短事务校验lease后提交并释放行锁）与
`commit_step(ticket,…)`（短事务重新加锁；epoch/行revision/lease owner/stop任一变化即
`DIRECTOR_RUNTIME_LEASE_STALE`且零写入）。executor的start/resume按
claim→begin_step→提交→锁外图步骤/网络→commit_step→投影→提交执行；stop仍先持久化停止意图。
剩余缺口：`domain_tools.py::submit_execution`仍开独立session调用ProductionAuthorizations并commit，
新多流程并发下的完整锁序与外发许可重验随I3/I2b接线；async heartbeat续租循环仍未实现（见上节）。
agent_harness使用同LangGraph model/tools循环，其原有调用回执必须保留。

同时读production/application/commands.py：ProductionCommands注入session，**调用方拥有commit**；
生产服务并非必须自行打开事务。本文上方“生产命令入口拥有自己的事务”是旧概述，
不能据此设计成在持有Project/Run锁时开启另一个会话争抢Project锁。

目标：由受限的入站装配适配器拥有一次短受理事务，调用Director域的资格校验与Production域的
既有授权受理，各域分别写自己的事实；Production不import Director，不读取其ORM，不获得LangGraph状态。
同一受理事务内资格/消费授权/NodeRun/Outbox/attempt回执原子提交，之后才由生产Worker做网络操作。
禁止“先检查epoch提交事务，过一段时间再无条件submit”的竞态窗口。

物理接线沿现有app/workers下的Director任务装配，注入中立Admission/Production端口到Director，
不把业务规则搬进Worker，不另建无限依赖的composition包。API仅接纳/排队新的异步Turn，
显式手动生产仍用现有入口。具体端口与允许import已在本节及MODULE_BOUNDARIES登记，测试消费者按RT01–12落实；
不能借重命名文件洗掉既有架构债务。

### 必须保留的用户门与恢复语义

计划Apply、内容Apply、直接编辑Save、新生产授权、Formal、Export各自有效；一次批准不能扩散到其余动作。
新生产attempt一个命令、一个NodeRun，ExecutionReceipt继续只有node_run_id/graph_id/graph_version_id/
status/plan_fingerprint。响应丢失先按原command_key/hash查回执，unknown_submission没有自动重发分支。
多集/多镜头拆业务步骤；Flow部分成功保持成功分支，不能用重启整个图代替局部恢复。

事件/Redis只是通知，丢失后从持久Proposal决定、Flow/Attempt、原生产事实重建等待与唤醒。
每次resume先校验注册定义key/version/hash及当前计划资格，缺定义等待，不载最新版，不复活终态。
retain只保留原输入/定义不变实例，supersede/cancel不删除成功产物；新计划已确认也不自动Formal或导出。
全作品完成必须按D2注册predicate读取正式事实；未知结果、缺集、待用户判断不能称为成功。


### D3执行端口与短事务受理

中立协议放app/contracts：RuntimeControlPort、SupervisionPort、BusinessFlowPort、AuthorizedProductionPort、
TextInferencePort、DomainRead/Proposal ports。协议只含冻结DTO/错误，不import ORM、Provider、HTTP或Worker。
Director领域服务实现Run/Plan/Flow校验，ProductionAuthorizations实现生产批准消费，Provider适配保留原底层能力。

装配实现选择app/workers/director_adapters.py（目标文件），归既有backend_worker边界。
它只管理session/RLS/提交和注入，不保存业务状态、不调用自己的LLM策略、不新增队列/后台循环。
现有domain_tools中直接依赖Production的submit/query转为注入协议，领域判断分别留在原服务。
API接纳异步Agent后只提交Turn/wakeup；Worker内注入同一组端口。手动生产API仍独立走既有ProductionCommands，
不会因Director停止而不可用。文本adapter也在入站装配桥接现有Provider能力与中立DTO，不为类型转换放宽provider→contract门。
架构扫描现已允许backend_worker到director/production/provider/contract；不扩大任何ALLOWED或重建baseline。

生产受理端口输入：
{scope,turn_id,lease_epoch,run_id,run_epoch,plan_id,flow_attempt_id,authorization_id,command_key,payload_hash}；
scope只来自可信上下文。执行步骤：
1. 同一应用事务锁定目标Project，确认未删除/当前actor；重放已受理相同命令时只返回原回执，不解释为新发许可。
2. Director域校验Run/计划new或retain资格、attempt冻结输入、控制epoch与当前权限；拒绝则无生产写入。
3. Production域在同session核验原持久授权、冻结body/hash/profile版本/有效期并调用原submit；
   同Project锁的再次获取是本事务重入，不能在另一个session等待自己持有的锁。
4. 原Production服务产生NodeRun/Outbox，Director域一次绑定attempt.node_run_id与业务回执；
   整个事务由入站适配器commit。若任一步失败，两域写入一起回滚。
5. 返回既有ExecutionReceipt；后续媒体网络只由Production Worker处理。Graph步骤/网络不在此受理事务内运行。

新NodeRun排队不是已发送。Worker实际发送前重新检验项目/来源/目的地/批准范围的当前资格，
将原Operation的submission_started/admission持久化后才出网。Run停止若先于受理提交则受理失败；
先受理的NodeRun属于在途范围，停止请求登记其cancel_requested。发送准入与取消按同Project锁序列化，
已先提交发送标记的操作可能已计费，只核对/尽力取消，不伪称撤回。

### 统一锁序与无锁网络

所有触及多个项目的共享引用写入先发现完整输入集合，再按UUID升序锁涉及的Project，
源私有内容通过窄端口检查，不切换目标事务GUC读全源项目。集合变化则回滚并重试纯本地准入，
不能追加一个更小ID的Project锁而制造反序。

全局顺序：Project集合→ProjectCreativeProfile→项目策略head/来源Subject/KnowledgeEntry/
PublicPublication（各类内ID升序）→Proposal→MasterRun→Plan→Flow Instance→Step→Attempt
→Turn→RuntimeControl→生产授权→领域目标（FileRevision/Result/Asset/Shot/EditSession，按类型/ID固定顺序）
→Graph/NodeRun/Operation。顺序与现有ProductionAuthorizations先取grant再取Shot匹配。
只读无需全部取锁；写路径只取自己所需子集且不逆序。
跨project资格发现与内容读取分开，任何“先锁Shot再锁Run/Project”的旧路径须在相应切片修正，不声明当前代码已经满足。

源撤销只锁相关Project/Subject或共享Entry，不反向逐个锁消费项目；提交失效事件后由各消费方重算投影。
实际准入始终同步核验，所以投影延迟不能越权。读网络、LLM、媒体上传下载、FFmpeg、LangGraph整步不得持上述事务锁。
锁超时/死锁仅对尚未提交的本地事务有界重试，已可能发送的调用不属于可重试事务。

### Checkpoint接管与迟到写入隔离

短事务移除跨图行锁后，单靠lease守卫不足以保护checkpoint：旧Worker可能在新epoch接管后写“最新状态”。
新绑定状态版本使用按epoch分区的checkpoint thread_id：
dramaforge:{project_id}:{turn_id}:{runtime_execution_id}:epoch:{lease_epoch}。
现有0066 RLS检查前两段，仍适用项目隔离；另由Runtime校验完整Turn/execution/epoch，不信前缀即允许恢复。
旧状态版本保持原key，只读/原路恢复，不直接解释为新状态。

RuntimeControl新增checkpoint_ref JSONB?，存{thread_id,checkpoint_ns,checkpoint_id,state_hash,engine_version,
state_schema_version,lease_epoch,runtime_revision}，它是私有checkpoint的已提交位置指针，不复制图状态。
每个新claim获得新epoch与独立key；调用实例worker_id使用host/pid/每次处理随机nonce，
不能让同一wake-up重复投递被误认成同一个可并发持有者。
图只读取Control已提升的精确checkpoint_ref，禁止无checkpoint_id地读取跨epoch“latest”。

执行：读取已提交位置与业务回执→在新epoch key初始化可恢复状态→锁外执行→私有checkpoint落盘→
短事务重验epoch/stop/Run资格→CAS提升checkpoint_ref及Turn投影/settle。旧epoch的迟到checkpoint只能留在旧key，
不得提升；已经取得的模型结果只补原Invocation。接管不依赖旧Worker主动停止才能隔离状态污染。
初始化和恢复只能用已提交checkpoint及真实工具/Invocation/生产回执重建下一个安全边界，
不能直接以initial state重跑已可能发送的model/tools。引擎版本不兼容则stale，不能偷换最新版。

checkpoint私有库与应用库不做伪分布式事务，故障按下表处理：

| 崩溃位置 | 恢复规则 |
|---|---|
| 原调用prepared前 | 无外部调用，重建同一稳定命令的准备，不扩大授权 |
| prepared/发送前标记已提交 | 只有证明确未发送才可按原准入执行；不能因为Worker失联推定未发送 |
| submission_started后无结果 | 原Invocation/Operation为unknown_submission，停止新的该动作，不再Create |
| 领域回执已提交、checkpoint未写 | 从原回执补图观察状态，不重复Apply/生产 |
| checkpoint已写、应用指针未提升 | 未提升分支不作为当前状态；新epoch从最后提交点及真实回执恢复，旧分支只作诊断 |
| 应用指针已提升、通知未送 | DB扫描补同一cause/wakeup，读原指针与回执 |
| stop/新计划后旧结果返回 | 保存原调用证据/Artifact，禁止新epoch状态推进或自动Formal |
| checkpoint缺失/损坏/版本不符 | 返回CHECKPOINT_UNAVAILABLE/UNSUPPORTED，不猜测成功，不启用第二引擎 |

以上是新状态版本的目标合同。I2b必须用故障注入验证旧Worker晚写、新Worker接管、心跳丢失与每个提交缝隙，
通过前不能把旧跨图guard直接删除后宣称恢复可靠。


### 有界轮次、监督槽与自动资料分析

Turn.intent_snapshot增加服务端冻结purpose=user_request|supervision|flow_step；旧无purpose记录按原路径读取，
不回填成监督授权。新purpose写入后不可改；supervision须master_run_id，flow_step须attempt关联。
用户Thread计算槽只约束queued/thinking的user_request；等待提案时允许用户反馈，不用旧等待Turn重新thinking。
Run监督槽约束该Run的非终态supervision Turn，StepAttempt计算槽约束该attempt的非终态flow_step Turn。
三个槽服务于不同事实，不能用Thread槽阻止整个项目所有独立工作。

ensure_supervision_turn在Project→Run锁下：已终态目标拒绝新工作；同cause读原Turn/wakeup；
有活动监督Turn则给它追加去重cause，不另建；无活动Turn才以
supervise:{run_id}:{plan_revision}:{cause_id}创建Turn与wakeup，同事务提交。
部分唯一索引为监督槽提供并发兜底；待处理cause在原Inbox/Wakeup中，不能仅放进内存。
每轮完成后若仍有可推进工作才创建下一轮；等待用户/外部结果时不空转模型。步骤可并行，
模型/工具/生产新受理均在Run锁下从原事实累计核对限额，不能靠换Turn或计划重置已经消耗次数。

普通问答/进度不建MasterRun。上传后的单文件解析继续原有处理入口；需要多轮语义研究时，
用户“上传并分析/重新分析”动作可授权**固定、可预览的research_import_v1操作计划**：
范围仅本次文件修订、指定分析目的/模型与操作上限，不含Story/媒体生成/发布知识。
该动作的typed命令记录明确用户决定并沿原Proposal/Apply服务创建和采纳确定性计划，
origin为关联该用户动作的Agent Turn（有Thread），不伪造一次LLM推理或自批准AI生成计划。
UI须先显示处理范围及外发/费用许可；缺许可则保存原件并等待，不能用“自动分析”绕过发送准入。
批次内容变化、超出原范围、创作建议或真实付费新范围必须另行确认。D4/D6/D7细化此固定操作计划与用户回执，
O7仍要求控制/安全基础先启用；不把旧历史上传自动补成已批准MasterRun。

D8补齐多块本地处理：有限单步native提取仍复用原领域Worker；需持久分块恢复的PDF/OCR/音视频等
使用固定source_extract_v1操作流程，用户“上传并识别/重新识别”的明确动作授权本次文件修订、处理档和本地资源范围，
模型调用上限为0。origin按上述固定用户动作接纳为合法Thread/Agent Turn，不伪造LLM推理；实际本地处理仍在原领域Worker。
extract_only只确认本地提取目标；auto还需要语义研究时沿research_import_v1等待相应模型/外发/费用许可。
未配置Director文本模型不阻止确定性流程，但后台控制服务不可用时只保存原件并显示等待，不临时启第二处理Runtime。
业务Step代表整个受控提取动作，块级结果/hash/范围记入该Attempt.receipt_ref的有界追加证据，
FileRevision.status/attempt仍是唯一文件处理控制；不为每页建一个影子Job/NodeRun，不把纯读工具伪装成提取写入。
本地处理动作按注册domain-write/apply合同接纳，固定用户确认覆盖其处理范围，不让模型扩大页数/文件范围。
重启只复用同attempt/输入/processor合同下仍可验证的已完成块；缺失/冲突明确失败或按已声明本地重试上限处理。
跨取消/改输入的新attempt不能把旧快照改标成新执行，旧结果留历史；所有新块和最终current推进重验控制/来源资格。
超总输出/页数/时长上限明确不完整或不支持规模，不能靠分块次数无限绕过处理档，也不截断后报完整。

### 状态转换（未列出的不同状态边拒绝）

MasterRun优先级：保持终态→cancel→硬截止→pause→正式完成事实→活动工作→等待。
paused期间的迟到产物只更新事实观察，不直接成功。wait_reason按unknown_submission、
permission_revoked、policy_denied、definition_unavailable、input_stale、user_decision、
production_pending、resource_unavailable排列；详细等待列表是只读投影。

| MasterRun起点 | 合法目标 |
|---|---|
| planning | waiting、paused、stopping、failed |
| waiting | running、paused、stopping、succeeded、failed |
| running | waiting、paused、stopping、succeeded、failed |
| paused | planning（尚无计划）、waiting（有计划重新核对）、stopping、failed |
| stopping | cancelled（封锁及取消意图已持久化，不表示远端已取消） |
| succeeded/failed/cancelled | 无出边 |

Plan Apply必须非终态；暂停时可以保存新计划但保持paused，只有resume才回waiting/planning。
候选计划的decision_basis绑定Run revision/epoch/当前计划并纳入hash；仅生成候选不改变Run业务revision。
控制版本变化后通过完整重验生成新候选，不能在旧Plan上更新CAS参数，也不能让同内容去重永久返回无法再确认的旧basis。
新增verify仅在desired_state=run且waiting的已确认非空计划上执行；未满足记录核验回执，
不改为成功。旧成功命令重放可读原回执，不能复活终态。业务完成事件也须经过同一谓词检查。

| DirectorTurn起点 | 原有合法目标（保持20条） |
|---|---|
| queued | thinking、failed、cancelled、stale |
| thinking | awaiting_user、awaiting_execution、completed、failed、cancelled、stale |
| awaiting_user | awaiting_execution、completed、failed、cancelled、stale |
| awaiting_execution | awaiting_user、completed、failed、cancelled、stale |
| completed/failed/cancelled/stale | 无不同状态目标 |

同态patch沿既有白名单/CAS，终态可补原调用证据但不再执行。恢复Graph不把awaiting状态改回thinking。

| BusinessFlowInstance起点 | 合法目标 |
|---|---|
| pending | running、waiting、paused、cancelled、failed |
| running | waiting、paused、succeeded、cancelled、failed |
| waiting | running、paused、succeeded、cancelled、failed |
| paused | waiting、cancelled、failed |
| succeeded/failed/cancelled | 无出边 |

必需分支可修复失败时Flow waiting，不提早failed；可选步骤skipped要有注册条件或明确缩范围决定。
完成条件逐required Step真实核验，status列不是成功的唯一依据。

| Step起点 | 特定合法目标 |
|---|---|
| pending | ready（前置满足）、blocked（前置失效）、skipped（定义允许） |
| ready | running、blocked |
| running | waiting_user、waiting_execution、succeeded、blocked、failed |
| waiting_user | ready（有效决定）、blocked（拒绝/过期）、succeeded（无需生产的Apply已完成）、failed |
| waiting_execution | succeeded、waiting_user（待Formal）、blocked、failed、cancelled |
| blocked | ready（明确恢复且无未决副作用）、failed |
| 任意非终态 | cancelled、superseded、failed（受控不可恢复原因） |
| succeeded/failed/skipped/cancelled/superseded | 无出边 |

| Attempt起点 | 特定合法目标 |
|---|---|
| pending | running、failed |
| running | waiting_user、waiting_execution、succeeded、failed、unknown_submission |
| waiting_user | running（有效决定）、failed |
| waiting_execution | succeeded、failed、cancelled、unknown_submission |
| unknown_submission | waiting_execution、succeeded、failed（证实失败/未发送）、cancelled |
| 任意非终态 | cancelled；未明外部结果仍unresolved_external=true |
| succeeded/failed/cancelled | 无出边，只补原证据/解除已核实未决标记 |

supersede是Step状态，Attempt对应cancelled+plan_superseded。Attempt失败后新尝试使用新身份和当前授权；
同一个未知提交不能改为failed以释放槽。retain不改实例创建计划，后续Turn资格从当前计划精确保留清单读取。
终态成功分支不随上层cancel改写。RuntimeControl仍为active/waiting/stopped/completed/failed/stale，
claim只使合法active/waiting进入active；stop使active/waiting→stopped；settle按图结果写等待/终态；
stopped/completed/failed/stale不能再次claim。

### 持久信号与事实扫描

RuntimeSignalClaim保留原(signal_id,runtime_execution_id)身份、reason/reference/expected_revision；
补request_hash、outcome(applied|obsolete|NULL)、applied_runtime_revision和settled_at。
首次claim只表示已受理，不等于图已处理。崩溃后新lease可继续核对这个原claim，
不得因为旧lease_epoch已变化就生成新cause或重复副作用；请求内容不同冲突。
提升Control checkpoint_ref、Turn投影、claim applied结果在同一事务；过期决定标obsolete，保留原因。
事件先于图提交、重复事件、乱序事件均据业务事实和claim核对，不相信队列中的成功标志。

原reconcile跳过Agent、要求恰一NodeRun，且只处理部分生产/Formal等待，需扩展为注册事实扫描：
ProposalItem决定、Run当前计划、Flow等待输入/attempt原命令回执、研究清单、知识/资产限制、正式选择/Export。
扫描按updated_at/id键集和有界批量执行，通过已有dispatcher/worker任务，不启动新调度服务。
每个cause使用稳定事实ID+事实revision；扫描只发去重wake-up，不调用模型或重新提交生产。
没有事件时可从事实重建cause，不能要求EventLog永久保留才能恢复。事实不存在/权限撤销明确等待或stale。

### 完成谓词与限额

D2及D8补齐的七类predicate由服务端注册（含独立资产采用/本地提取），输入采用严格DTO且不接受predicate_results/succeeded字段。
验证先取得同一已确认Plan及输入版本、解析正式输出槽，再按相同Project/目标锁序核对。
predicate必须检查其数据仍可用、范围/版本符合、用户决定有效；完成回执带事实ID/版本/hash，
同事务CAS标Run成功。期间Plan/epoch/源状态变化则核验失败，不能用旧快照写成功。

research_ready允许已检查类别none，拒绝incomplete；episode/project交付核对指定所有集与MP4/SRT，
一条Export或Flow成功不能代表完整作品。技术成功和文化/美术人工判断分别纳入目标要求，
缺少必须人工判断则waiting/user_decision，不由LLM打分代替。

限额包含Run累计model/tool/step/max_provider_calls、并发和deadline；所有新增调用先在Run短事务锁下检查
原Invocation/ToolCall/Attempt/Operation，分配唯一事实身份。prepared/unknown仍占已预留次数，
只有明确未发生且未保留有效操作的拒绝才不消费；取消/切计划不能“退款”后盲重发。
并行上限先按设备配置保守运行，可调不等于无界。原Agent每Turn的6模型/12工具/120秒护栏继续，
长期目标通过新有界Turn推进，不能通过拉长单次Graph越过护栏；无金额/余额/credits新系统。


### 内部接口合同与注册流程

| 端口 | 冻结输入/返回 | 原子性与拒绝 |
|---|---|---|
| bind | scope,turn_id,engine_version,state_schema_version → runtime_execution_id,binding,revision | 同绑定读回；异绑定ENGINE_BINDING_CONFLICT；不由模型挑engine |
| claim/heartbeat | scope,execution_id,unique_worker_id,ttl / Lease → Lease/expires_at | DB时间与当前epoch；LEASE_BUSY/EXPIRED；建议新版本300s TTL/30s heartbeat须I2b实测 |
| check/settle | scope,Lease,run_epoch,instance_id? / status,checkpoint_ref,expected_revision → revision | check只读不授长期资格；settle CAS、旧epoch拒绝，不能复活Turn |
| claim_signal | scope,Lease,signal_id,expected_runtime_revision,reason,reference_id → new/replayed/applied/obsolete | request_hash绑定完整payload，异输入SIGNAL_CONFLICT；applied须有应用提交证据 |
| request_stop | scope,turn_id,expected_revision,request_key,reason → accepted control revision | 明确用户/上层授权；fence+StopRequested同事务，重复返回原决定，不声称远端取消 |
| ensure_supervision_turn | run_id,plan_revision,cause_id,observed_epoch → turn_id,created/busy | Run锁+部分唯一；actor从持久Run核验，不能从事件伪造 |
| AuthorizedProduction.submit/query/cancel | 冻结Scope+attempt+grant+command_key/hash / 原command或run_id / cancel键 → 原Receipt/事实 | submit按原子受理步骤；query无副作用；cancel只登记原任务意图 |
| TextInference.prepare/execute/query | frozen model/connection+turn/invocation_key+context/schema/tool hash → Invocation及规范化结果 | 原Invocation唯一；发送前准入、网络锁外；未知提交不自动execute |
| Research.apply_analysis | 可信调用证据+file/extraction/attempt+typed结果 → 不可变Analysis回执 | 领域只写研究；重复原回执，不由客户端自报model origin |
| Predicate.verify | 当前计划及服务端解析的事实引用 → satisfied,observations,waits | 仅注册kind，当前资格/版本重验；不写Formal/Export，不访问自由SQL |

request_stop内部幂等复用Turn控制事实与已有stop_requested_at/epoch，完整Run控制回执由MasterRunControlReceipt拥有；
单Turn stop相同意图读当前已停止事实，不能因重放增加epoch。它不是新通用控制回执表。
返回的revision用于后续CAS；API层精确错误/响应在D7统一，不能泄露不存在/跨项目对象差异。

BusinessFlowDefinition的注册项由代码构造并冻结：
key/version/contract_hash、输入/输出schema、步骤模板、effect_class、required与完成predicate、
resume规则、用户门、graph_entrypoint。input只选择业务对象/范围，不得改拓扑或用户门。
服务根据已采用Script/Episode/Shot集合展开步骤实例，展开结果参与hash；集合改变先新计划并明确处置原实例。
冻结定义不可原地改写；缺版本waiting/definition_unavailable，绝不取最新版本替代。

| 首期注册流程 | 可执行阶段与输出 | 必须等待的决定 |
|---|---|---|
| source_extract_v1 | 明确原件修订→有界本地分块→不可变Extraction与来源定位 | 固定本地处理范围；模型调用为0，控制服务恢复不能假装需要聊天模型 |
| research_import_v1 | 原件/解析→逐文件研究覆盖→差异/上下文提示 | 输入处理与外发/费用许可；用户修正不被分析覆盖；不发布知识 |
| story_development_v1 | 研究依据→方向比较→讨论→剧本/分集/场镜提案 | 方向与typed内容Apply；失败保留已有正式脚本 |
| asset_preparation_v1 | 设定提案→固定公共引用/项目变体→待生产或用户采纳 | 设定保存、生产授权、采纳；引用不会自己生成 |
| animation_promo_v1 | 主题表达→脚本/分镜→逐镜生产→审片→剪辑/交付 | 所有原用户门；检查宣传重点与人工文化判断 |
| single_comic_v1 | 一集完整剧本→角色/对白→逐镜生产→单集交付 | 单集结构/角色/Formal/Save/Export |
| serial_comic_v1 | 全剧共享设定→分集安排→每集子步骤→逐集交付 | 全剧/分集采用及跨集变更影响；不可把一个集状态当整剧 |

这是一个执行体系的七种注册业务定义，不是七个Runtime。图内只做有界调度/读事实/调用端口，
长期等待持久化后退出Worker槽。媒体create的effect_class不能通过“read”工具或Skills标签降级，
repair登记与repair真实生产是两个明确动作。任何新定义必须给出输入/输出/完成/恢复/用户门测试才可注册。

### O2正式命名与现有消费者

按事实原地改名，不跨域整体搬目录，不留同义DTO兼容层：
- contracts/registry/library/resolver中的WorkflowTemplate* → ProductionTemplate*，纯元数据不恢复graph_factory。
- workflow_read_models的ShotWorkflowState/WorkflowOverview等 → ShotProductionWorkflowState/
  ProductionWorkflowOverview；scene_orchestration的正确SceneProductionStatus保留。
- layered_planning/continuity/quality_report/shot_complexity/character_participation/reference_capability
  继续表达创意规划/连续性/质量/身份事实，不误改成Template或BusinessFlow。
- 前端WorkflowNavigator→ProductionWorkflowNavigator；workflow-api拆为生产投影与创意能力客户端，
  QueryKey/SSE失效/路由调用同时更新；公开DTO从OpenAPI重生成。
- wire端点统一在D7改为显式production-workflow名称并更新全部调用者；不是新建通用template执行API。
  旧workflow_template_key属于冻结历史输入，仅在其原schema版本内读取；新版本写production_template_key，
  不重算旧hash、不把旧snapshot自动升级执行。
- turn_kind='workflow'保持原有不同事实；停止禁止“所有workflow字符串”的粗暴扫描。
  新业务编排统一BusinessFlow，旧DirectorWorkflowRun等退役表面仍不可恢复。

### D3验证矩阵

| Case | 必须证明的行为 |
|---|---|
| RT01 | 旧Agent v1/固定图v1、新Agent v2/固定图v2各选择正确唯一adapter，未知/双绑定拒绝；旧Agent有execution ID也不被错误转Control |
| RT02 | 同Turn重复投递唯一持有者；新nonce接管不能与未过期lease并行；stop立即fence，迟到结果只补证据 |
| RT03 | 新旧epoch checkpoint隔离；未提升分支不可作为最新；损坏/缺定义停止，无静默迁移 |
| RT04 | 每个checkpoint/应用/网络提交缝隙故障，原Invocation/命令回执恢复；unknown_submission零重复Create |
| RT05 | Run/Thread/Step槽各自并发约束；多个独立步骤可受控并行；cause丢通知/重复/乱序不丢决定 |
| RT06 | Project/Run/授权/NodeRun/Outbox/attempt一事务受理；任一失败全部回滚；取消/计划变更竞态有确定先后 |
| RT07 | Turn全部20合法边、36非法跨态、8同态patch；Run/Flow/Step/Attempt所有列出的边及终态拒绝 |
| RT08 | retain/supersede/cancel连续换计划、部分成功、旧未知提交占槽，成功产物不变 |
| RT09 | 当前plan的全部正式完成谓词；零发现/缺集/未Formal/未Export不得伪成功；客户端结果字段拒绝 |
| RT10 | Worker文本经过同一模型身份/工具授权/项目外发；拒绝后零后续调用，媒体仍只走Production |
| RT11 | 跨Turn/换计划限额不能重置；等待不空转模型，真实权限撤销后不继续行动 |
| RT12 | 手动生产在Director停用时仍可用；O2更名更新所有消费者，无第二实现/新增跨层债务 |

本矩阵是D7/I阶段的测试输入，当前未运行。D3交叉检查必须把以上规则与DATA_MODEL索引、
MODULE_BOUNDARIES、Production受理/外发以及D1确认节点核对后才能判定设计退出。

### D3审查结论

设计审查通过：O1–O7逐项对应目标/命名/两Runtime/外发门/Worker文本/控制切换/资料接入顺序；
Run、Turn、Flow、Step、Attempt及控制状态边已区分；受理、发送和checkpoint提交缝隙有确定恢复规则；
入站适配使用当前允许依赖，不新增跨层豁免；O2保持三类事实和退役边界。D2新增控制指针/claim结果/槽索引已回填。
源码审查纠正了旧Agent已经有execution ID、授权锁早于Shot、Production caller-owned commit及reconcile覆盖有限四点。
RT01–12为可执行验证输入，当前没有运行通过证据。下一步D4补逐格式资料/研究/上下文合同，D5补实际出口，
D7落实精确API和测试文件；最终实现与故障恢复必须实测，不能以本节设计审查代替Full或真实运行验收。
