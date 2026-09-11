# DramaForge V1 实施方案

**版本：2026-09-09 · 导演 Runtime 独立与选型修订**  
**配套设计：DramaForge_V1_设计方案_20260907.md（内容版本 2026-09-09）**  
**核查基线：dev@4de7acd14481e262346fb0a4802d7725586194ed**  
**执行范围：既有 V1 的 Runtime 边界修订 D0–D8；不是重新实施 R0–R8。**

## 1. 交付目标与实施决策

完成以下闭环：

> 用户请求 → 独立导演轮次 → 有界模型/工具循环 → Proposal / 用户决定 → 稳定业务命令 → 既有生产 Runtime → 持久事实通知 → 导演恢复到下一确认点。

主选 Python LangGraph，生产仍用既有 NodeRun / Outbox / Arq / ProviderOperation / Artifact。保留 Pi 为首要备选；Claude Agent SDK 为 Claude 主导产品路线的备选。先拆业务边界，再验证并启用框架，不能把“安装成功、能对话”作为 Runtime 交付。

本文件给出具体实施与验证工作，**这些 D 任务尚未在项目中执行**。本轮实际完成的是源码与官方资料复核、两份 Markdown 修订；未修改应用、台账或运行环境。

## 2. 基线校正：不要把已完成任务重做

### 2.1 原 R 任务与本次增量

| 原任务 | 当前登记 / 相关实码 | 新任务应做的增量 |
|---|---|---|
| R0 基线校准 | 台账 COMPLETE | D0 登记本次修订、冻结新基线 |
| R1 Scene 工作流 | 台账 COMPLETE | D6 验证两侧状态分开、草稿不被异步续接覆盖 |
| R2 真实文本导演 | 台账 COMPLETE；已有 text_transport、Story/Shot/Editing 调用 | D3 拆调用职责，D5 转入独立 Worker |
| R3 有效创作意图 | 台账 COMPLETE | D6 保留上下文编译与优先级，防止框架默认记忆覆盖 |
| R4 有限推进和用户决定 | 台账 VERIFIED；已有 Turn、NextAction、业务检查点 | D1/D2/D5 拆耦合，建立唯一 Runtime 推进者 |
| R5 恢复矩阵 | 台账 VERIFIED | D7 新增跨 Runtime、检查点和唤醒故障矩阵 |
| R6 Final Film/SRT | 台账 VERIFIED；R6 合同已有实现和同候选证据 | D7 保留 MP4/SRT 冻结与零媒体重生成回归 |
| R7 双路径真实验收 | 台账 COMPLETE | D8 对新 Runtime 候选重验受影响路径 |
| R8 发布准备 | 台账 COMPLETE — READY FOR OWNER MERGE | D8 为新候选独立绑定证据，不复用旧 PASS |

固定 SHA 的 Goal 状态是 GOAL_READY_FOR_OWNER_MERGE，列明 runtime candidate adf1b9434f59f7dfacf5819d04a77997244e783e、evidence/release candidate 3677430a75bb92a588a5304508eaff02a278bf03 和 PR #66。本文不把登记状态升级为“已部署”“已合并”或本轮亲测。

### 2.2 已确认的改动靶点

| 现有路径 | 需要处理的事实 |
|---|---|
| backend/app/api/v1/workbench.py | 生产写路径 commit 前调用 DirectorBusinessCheckpoints |
| backend/app/director/business_checkpoints.py | 导演跟踪与业务写事务同 Session |
| backend/app/director/next_action.py | 直接读取 NodeRun/GraphVersion/ProductionGraph 内部结构 |
| backend/app/director/text_transport.py | 轮次创建/claim/推进与模型请求、审计混合 |
| backend/app/director/turn_service.py | 新引擎启用后需收敛为控制/业务服务，不能继续独立推进同轮次 |
| backend/app/workers/default.py、jobs.py | 导演恢复和生产任务共用注册/启动路径 |
| backend/app/events/outbox.py | 已有租约/重试/发布状态；published 不等于各消费者完成 |
| backend/app/production/workbench_execution.py | 已有执行回执/作用域锁，优先扩展复用 |
| backend/pyproject.toml | 当前 Python 后端未登记 LangGraph；需在验证后锁定依赖 |

执行开始时重新读取实际 dev 和当前 Task Contract。如果代码已漂移，先更新差异表，不机械重复本文描述的修改。

## 3. 工作包、顺序和边界

| 任务 | 产出 | 前置依赖 | 退出条件 |
|---|---|---|---|
| D0 基线与任务登记 | 修订入口、差异表、候选/历史证据映射 | 无 | 不混淆旧 V1 成果与新 Runtime 工作 |
| D1 契约与依赖边界 | 命令/回执/读事实/事件/RuntimePort 契约 | D0 | 生产不依赖 SDK 私有类型，关键 Gate 可测试 |
| D2 事务解耦与持久唤醒 | 生产事件、导演 Inbox、唤醒记录、独立消费 | D1 | 导演失败不阻断生产提交，崩溃不丢续接 |
| D3 文本调用拆分 | InvocationService、TextModelPort、稳定调用记录 | D1 | transport 不再拥有轮次推进事务 |
| D4 Runtime 验证与选型锁定 | LangGraph 垂直切片、ADR、兼容/恢复报告 | D1、D3 | 全部硬门通过；有具体依赖版本与失败记录 |
| D5 独立导演执行与迁移 | 独立 Worker/队列、检查点、engine 路由、在途策略 | D2、D3、D4 | 新轮次独立执行，旧轮次单一引擎排空 |
| D6 工具、用户决策与 UI | 接入现有 Proposal/执行入口、上下文、状态展示 | D5 | AUTO/ASSIST/MANUAL 和确认点语义正确 |
| D7 故障与回归 | PG/Redis/Worker 故障注入及产品回归证据 | D6 | 无重复生产、无旧授权执行、无事实污染 |
| D8 新候选与交付 | 双路径验收、source/image/证据、评审材料 | D7 | 形成可审阅的新 Runtime 候选和明确发布状态 |

D2 与 D3 在契约固定后可独立实施；D4 的流程原型可使用模拟生产服务，但不能以此替代 D7 的真实进程与数据库验证。本文的工作包分工不要求多 Agent 并发执行。

## 4. D0：冻结基线并登记本次修订

### 4.1 操作

1. 阅读仓库 AGENTS.md、七方案入口和本任务对应合同；按现有权威顺序定位受影响章节。
2. 把这两份修订作为用户当前要求登记到既有 V1 入口，不另建平行总规划，不修改七份原始来源完整性文件。
3. 保留原 R0–R8 的完成记录，为 D0–D8 建立有界 Task Contract；首次登记为 PLANNED/IN_PROGRESS，不能沿用原任务 PASS。
4. 冻结 source SHA、依赖锁摘要、迁移 head、后端/前端运行身份及现有证据入口。
5. 只读确认实际环境身份；若需要隔离验证环境，明确其项目、数据库和镜像与用户当前环境的关系。
6. 记录需保护的用户输入、当前在途 Turn/NodeRun、候选与 Formal。不能清理它们来制造“干净基线”。

### 4.2 产出

建议在现有 task-contracts 目录登记 V1-D0-RUNTIME-BASELINE-20260909.md，记录：

- 本次用户修订的职责边界和选型；
- 现状、目标、非目标及证据时点；
- 原候选与新候选的独立验收关系；
- 明确“Production Runtime 唯一”不等于“导演必须纳入 NodeRun”。

本轮不因写合同自动触发 merge/deploy 或付费调用；后续实施沿已有有效授权推进，不重新询问已获授权事项。

## 5. D1：先固定业务与 Runtime 契约

### 5.1 建议代码归属

下列新增目录/接口为目标结构，实际命名在合同中统一：

| 归属 | 内容 |
|---|---|
| app/contracts/director_runtime.py | RuntimeInput、ResumeSignal、RuntimeView；无 SDK 类型 |
| app/contracts/production_commands.py | Typed command、Receipt、错误代码 |
| app/contracts/production_facts.py | ExecutionFact、CandidateFact、FormalFact、ExportFact |
| app/contracts/domain_events.py | 事件 envelope、版本与 payload |
| app/director/runtime/ports.py | start/resume/request_stop/read 的应用接口 |
| app/production/application/ | 命令与查询实现，复用当前业务服务 |

不为这些接口重建 Project/Scene/Shot/NodeRun/Artifact 表。不将生产 ORM 暴露给导演，仅由生产侧实现 DTO 查询。

### 5.2 业务命令的硬约束

- command_key 由可信应用在首次提交前持久化，绑定 action identity、request hash、授权与事实版本。
- key 的唯一作用域与现有 receipt 机制一致；若扩展到不同 command_type，必须显式避免跨类型碰撞。
- 同 key 同输入返回同回执；同 key 不同输入返回冲突。
- command_type 为白名单，包含准确 target 与 expected_versions，不接受模型生成的自由命令。
- workspace、project、actor 从可信调用身份解析，校验目标所属关系。
- authorization_ref 指向可独立核验的业务决定或授权记录，不能要求生产读取 SDK checkpoint 才能鉴权。
- 写操作再次校验锁定字段、版本、plan_fingerprint、模型绑定和有效授权。
- origin 中的 turn_id 只用于溯源；手动调用无需拥有 DirectorTurn。

拟定业务工具：read_project_context、read_production_status、create_proposal、apply_proposal、request_stage_execution、request_repair、request_export。write 工具均调用现有业务 Gate；工具可见不等于拥有执行许可。Formal 确认保持用户现有入口，不交给模型自由决定。

### 5.3 Runtime 应用接口

| 操作 | 输入 | 返回与语义 |
|---|---|---|
| start | turn_id、作用域、冻结输入引用、engine_version | 受理身份；通过持久调度运行 |
| resume | turn_id、signal_id、原因、事实版本/决定引用 | 重复 signal 幂等；不接受任意框架 state 注入 |
| request_stop | turn_id、actor、expected_revision | 持久控制请求；不假装生产已取消 |
| read | 授权作用域、turn_id | 用户可理解的状态、等待原因、建议/执行引用 |

LangGraph/Pi/Claude adapter 放在 RuntimePort 后面。接口是迁移缝隙，不承诺三个引擎的原生检查点可以互转。

### 5.4 验收

1. 生产契约无 LangGraph/Pi/Claude 类。
2. 导演核心模块不能 import NodeRun/GraphVersion/ProductionGraph ORM 或具体媒体 adapter。
3. 生产写服务不能 import DirectorTurn、DirectorBusinessCheckpoints 或导演 Runtime。
4. 同 key 重放与 payload 冲突使用真实 PostgreSQL 唯一约束验证。
5. 用户修改/撤销与生产受理并发，结果符合单一受理顺序。

架构依赖测试只覆盖这些高风险边界，不为每个 DTO 字段写镜像式测试。

## 6. D2：解除生产事务对导演的依赖

### 6.1 改动步骤

1. 在现有生产受理、Formal 修改、终态完成等业务事务中登记对应事实事件；能复用现有事件就复用。
2. 受理事务同时保存命令回执、执行事实及必要 Outbox。失败一起回滚，成功不要求导演可用。
3. 删除 workbench 写路径中对 track_execution/reconcile_business_fact 的同步等待。
4. 把当前 DirectorBusinessCheckpoints 的业务跟踪逻辑移至导演事件消费路径，重新读取正式读接口。
5. UI 在生产受理后使用 Receipt/生产快照更新状态；导演跟踪允许短暂滞后，不能影响本次成功响应。
6. 补上 durable Inbox 与 wakeup 记录，使用独立消费进度。
7. 为事件丢失、进程中断、消息系统短暂不可用保留补偿扫描；扫描产生唤醒，不直接调用模型或再次创建媒体任务。

### 6.2 Inbox / wakeup 建议字段

| 记录 | 最小字段和约束 |
|---|---|
| director_event_inbox | consumer_id、event_id 唯一；project/workspace、aggregate/version、received_at、processing/error、payload 引用 |
| director_wakeup | wakeup_id、turn_id、原因、来源 event/decision、epoch、next_attempt_at、lease_owner/expiry、attempt、状态 |
| 消费水位 | 以目标 aggregate 的版本为准；不能用不同对象不可比的数字强行统一排序 |
| 死信 | 原事件/唤醒身份、错误分类、尝试历史、重放记录 |

名称和是否复用已有表在 D1/D2 合同确定；不允许仅用 Redis 瞬时 job ID 表示“后续一定会执行”。

### 6.3 提交与 ACK 顺序

1. 读取消息并校验 envelope/作用域。
2. 开启导演侧事务，以唯一键插入或读取 Inbox。
3. 持久保存待处理唤醒；重复事件不重复建立副作用动作。
4. 提交数据库事务。
5. ACK 消息。
6. 独立 dispatcher 将可用唤醒入导演队列，失败可补偿。
7. Worker claim 唤醒并获取轮次租约，执行一段有界流程。

事件 received 与 processed 分开：进 Inbox 不等于 Runtime 已恢复。只有处理完对应结果或明确终止才推进处理状态；单个事件可影响多个轮次，必须逐目标保存交付结果。

Outbox 发布重复在至少一次投递系统中允许；业务消费通过 Inbox 幂等。不能根据现有 Outbox 的 PUBLISHED 值宣称端到端 exactly-once。

### 6.4 必需测试

| 注入位置 | 期望 |
|---|---|
| DirectorBusiness 逻辑抛异常 | 生产受理/Formal 成功不依赖它 |
| 生产事务回滚 | 不出现已发布但没有业务事实的有效事件 |
| 生产已提交、发布前退出 | dispatcher 恢复后发布 |
| publish 成功、标记前退出 | 允许重投；消费者最终只产生一次动作 |
| Inbox commit 后、ACK 前退出 | 重读消息不重复推进 |
| Inbox commit 后、Arq 入队前退出 | 持久 wakeup 被补发 |
| 事件乱序/重复 | 最新事实不被旧版本覆盖 |
| 导演消费者停止 | 生产任务正常推进；导演恢复后补齐状态 |

使用真实 PG/Redis 验证关键崩溃窗口。Outbox 文件中的默认 StreamPublisher 是内存实现，测试不能把 fake 的 messages 列表当作真实跨进程证据；检查实际部署注入的 publisher。

## 7. D3：把文本调用从轮次管理中拆出

### 7.1 保留与迁移

保留现有 ModelBindingResolver、TEXT_GENERATE、TextGenerateRequest、输出 Schema、脱敏审计、用量与成本来源。现有 LiteLLM 接入可继续作为 TextModelPort 实现，无须引入另一个模型目录。

将 text_transport.py 中的职责拆为：

| 目标部件 | 负责 | 移除的职责 |
|---|---|---|
| ContextBuilder | 冻结有效事实、意图和上下文 | 不推进 Turn |
| InvocationService | 创建调用身份、状态、输出与用量审计 | 不创建生产任务 |
| TextModelPort | 标准文本请求/响应/错误 | 不 commit 业务 Session |
| Runtime adapter | 调用顺序、步骤限制、等待与完成 | 不复制 Proposal/NodeRun 真相 |
| Proposal service | typed diff、版本、业务应用 | 不负责模型网络连接 |

### 7.2 调用持久性

现有 Turn 中只有一次 transport 的汇总字段。新增多步调用支持前，评估是否需要 director_invocations 子记录；如果现有审计表可表达则复用。每次调用至少记录：

- turn_id、invocation_key、step identity、attempt；
- 模型 binding/具体模型/连接身份摘要；
- 输入 hash、Schema 与意图版本；
- prepared/submission_started/completed/failed/unknown_submission；
- 已验证输出引用、token usage、cost_status、错误分类。

invocation_key 在调用前持久化。一次确定的重放查询原记录；只有经策略允许的新尝试才创建新 attempt。结构修复是单独可追踪的调用，不隐藏费用，也不能绕过最大次数。

### 7.3 失败策略

- 未提交且明确可重试：有界重试，保留模型身份。
- 提交开始后失联：先核对上游可查身份；无法查明时标记未知/失败待处理，不能自动重复收费调用。
- 已有经验证响应：检查点恢复复用该结果，不重新问模型。
- 结构不合法：最多一次修复；仍失败则提供真实错误，不用规则模板伪装 AI 成功。
- 文本模型配置缺失：明确受阻，手动生产继续。
- 用户事实已变化：输出可留审计，但提案不可直接覆盖新事实。

### 7.4 验收

测试真实入口映射、绑定保持、用量 unknown/reporting、结构修复上限、响应持久化后崩溃复用、stale 结果不可应用。模型集成测试使用已配置通道；模拟结果只证明控制流，不能标为真实导演质量验证。

## 8. D4：Runtime 验证与选型锁定

### 8.1 决策依据

当前项目需要持久等待、恢复和业务 Gate，且后端主要为 Python。因此主选 Python LangGraph。它负责流程位置和暂停恢复；业务工具、授权、事件、回执仍由应用提供。此选择不等于比较过三者的创作质量或性能。

- [LangGraph 官方概览](https://docs.langchain.com/oss/python/langgraph/overview)：用作主选能力依据。
- [Pi agent-core 官方文档](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)：用作可组合 Agent loop 备选依据。
- [Claude Agent SDK 官方概览](https://code.claude.com/docs/en/agent-sdk/overview)：用作完整 harness 备选依据。

先完成主选切片与硬门。若主选硬门失败且不能在有界任务内解决，或团队明确转向开放式工具 Agent/Claude 产品路线，再制作对应备选薄适配器。**不要求先实现三套完整 Runtime，也不以没有实现备选为由伪造胜负。**

### 8.2 LangGraph 最小垂直切片

场景采用一个已存在的 Shot，不创建新影视数据模型：

1. 通过 RuntimePort 创建一个 DirectorTurn。
2. ContextBuilder 读取已保存事实。
3. 模型经 TextModelPort 提出一个白名单只读工具动作或 typed 建议。
4. 工具读到结果后最多再进行有限推理，形成 Proposal。
5. 持久 interrupt，释放 Worker。
6. 用户接受/部分接受/拒绝形成领域决定，再唤醒。
7. 通过业务 Gate 提交一个已授权阶段命令，获取 stable Receipt。
8. 持久等待生产；模拟完成事件可以用于早期控制流。
9. 恢复后读取当前事实，到“确认候选”或其它既有下一确认点停止。
10. 分别在暂停、命令受理后、结果持久化后强制结束进程，核对重启行为。

最终 D7 使用真实 PG、消息系统和生产执行替换模拟端口验证。

### 8.3 若评估 Pi

优先使用 agent-core，按需要评估 SDK 的会话/压缩能力。通过 TS 导演服务实现相同 RuntimePort 和领域工具，不重写 Python 生产服务。

需要额外证明：

- TS 服务可在平台重启后恢复业务等待，而非仅恢复对话文本；
- 模型注册、实际模型身份与现有绑定保持一致；
- tool_call_id 只作关联，不独自充当可重放 command_key；
- transcript/compaction 不丢失拒绝记录、授权边界或版本依据；
- 默认文件系统工具与扩展发现按产品作用域显式配置；
- 调用前后事件 hooks 的持久化时机与进程中断窗口有测试。

Pi SDK 已具备会话等功能，不能写成“完全没有持久化”；需要补证的是它与 DramaForge 事务和唤醒的结合。来源：[Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)。

### 8.4 若评估 Claude Agent SDK

采用 Python SDK 亦可，不因语言否决。通过自定义业务工具调用相同命令/读接口，并验证：

- 模型产品前提是否为 Claude；不能把网关兼容推导成支持任意非 Claude 文本模型；
- SDK 运行进程、实际 bundled binary、依赖版本及容器身份可追踪；
- session_id 与领域 Thread/Turn 映射清晰，多租户目录/配置/会话存储隔离；
- 使用受控工具集，生产通过业务接口，不由 shell/文件工具绕过发布；
- 会话持久化、进程重启、停止/恢复、用量和业务命令幂等都达到相同硬门。

Claude SDK 存在外部会话存储能力，不应以“仅本地会话不可恢复”否决。其 session 保存的是 Agent 会话，业务回执仍由项目持有。来源：[sessions](https://code.claude.com/docs/en/agent-sdk/sessions)、[hosting](https://code.claude.com/docs/en/agent-sdk/hosting)、[LLM gateways](https://code.claude.com/docs/en/llm-gateway)。

### 8.5 所有引擎统一硬门

| 编号 | 验证项 | 通过条件 |
|---|---|---|
| H1 | 人工等待后跨进程恢复 | 无浏览器依赖，恢复到正确业务确认点 |
| H2 | 命令受理后 crash/replay | 原 key、原 receipt；无额外生产 create |
| H3 | 重复/并发 resume | 同一 epoch 同一 Turn 只有一个有效推进者 |
| H4 | stale/撤销/切 MANUAL | 下发前二次 Gate 拒绝旧动作 |
| H5 | 多租户 | 任意猜测 execution/thread ID 均不能跨项目读取或恢复 |
| H6 | 模型身份 | 配置、实际调用、审计一致；无静默换模型 |
| H7 | 停止与步数限制 | 无进展或达到上限后结束/暂停，不无限循环 |
| H8 | 业务状态唯一 | SDK 状态不直接生成 Formal/Artifact/业务成功 |
| H9 | 等待释放资源 | waiting 时无持续模型请求、无占用中的长作业 |
| H10 | 可观测与版本 | invocation、turn、command、run 的关联与 engine/state 版本完整 |

选型报告记录 PASS/FAIL/NOT_RUN，并列出实际代码量、集成复杂点、首响应/完整步骤延迟、冷启动与内存测量。没有实测的数据留空，不给武断的性能排名或虚构评分。质量比较只在相同上下文、工具、可比模型设置下进行；不把模型差异算作框架优势。

## 9. D5：独立导演 Worker 与检查点迁移

### 9.1 目标代码与部署范围

| 范围 | 变更 |
|---|---|
| director/runtime/langgraph_runtime.py | 目标 adapter，封装图与 resume，SDK 类型不外泄 |
| director/runtime/state.py | 流程状态引用、版本、等待条件，不复制生产事实 |
| director/runtime/projector.py | 将进度投影到既有 Turn/API 可读状态 |
| director/runtime/control.py | 单一租约、fencing epoch、持久 stop 请求 |
| workers/director.py | 独立 Worker 设置、恢复与唤醒消费 |
| 既有 default/jobs | 移除新引擎轮次的导演推进注册；保留生产任务 |
| 依赖/镜像/Compose | 增加已验证锁定依赖和独立启动角色 |
| 迁移 | engine/state_version/execution_id、必要调用记录、Inbox/wakeup 索引 |

不要新建第二套 ProductionGraph，也不将 LangGraph node 写成生产 GraphNode。导演流程图与影视生成图只是同用“图”这个概念，执行身份不共用。

### 9.2 检查点与状态

- 使用持久 PostgreSQL checkpointer，禁止生产配置退回 MemorySaver。
- runtime_execution_id 由服务端映射，按 workspace/project/turn 隔离。
- 产品 DirectorThread 是用户会话；框架 thread_id 是检查点键。V1 每 Turn 独立执行，跨 Turn 通过领域历史构建上下文。
- 图 state 保存输入/Proposal/command/invocation 引用、等待条件及算法需要的有限消息。
- 真实用户决定、Proposal 应用结果与生产事实仍在领域表。
- DirectorTurn.status 为投影，由当前引擎适配器收敛；旧 TurnService 不再独立根据生产状态推进新引擎轮次。
- 图 checkpoint 与业务事务分开，跨边界通过 action journal/receipt/invocation 恢复，不强行共享连接或模拟分布式事务。

LangGraph interrupt 恢复可能重进节点，具有副作用的步骤必须先核对 journal/receipt；不能把副作用放在未经保护的 interrupt 前。来源：[interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。

### 9.3 并发与租约

同一 Turn 的推进使用数据库 claim/lease 和递增 fencing epoch。工作单元开始、写关键结果和下发命令前核对当前租约/epoch；不能只依赖 Arq job_id。

检查点写入也要处理旧 Worker 迟到：在本次执行控制锁/受验证的单写机制下保存，过期执行不得覆盖新版本。若所选 saver 无法承接所需 fencing，则在 adapter 层提供受控写通道，或保持单写持有直到执行结束；不能假定框架自动支持项目所需语义。

租约丢失后阻止新动作。已经受理的远端操作通过稳定 key/receipt 核对，不因旧 Worker 迟到响应重复下发。强制测试“旧 Worker 暂停超时，新 Worker 接管，旧 Worker 又返回”的场景。

### 9.4 检查点访问控制

框架 PostgreSQL 连接池不会自动继承应用 SQLAlchemy Session 的 RLS 设置。任务必须明确：

1. 认证 API 如何解析并校验 workspace/project/turn。
2. checkpointer 的数据库角色、schema 与权限。
3. 同一连接复用时怎样设置/清理租户上下文。
4. 需要跨租户恢复的后台角色如何通过受控任务身份访问。
5. 应用业务角色能否越过 adapter 直接读取其它租户 checkpoint。

不能仅用 thread_id 带 workspace 前缀代替隔离。必须有不同 workspace、重复业务 ID、伪造 execution_id 和连接复用的集成测试。来源：[LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)、[数据库检查点示例](https://docs.langchain.com/oss/python/langgraph/add-memory)。

### 9.5 API 与调度

新启动入口完成鉴权、冻结输入、持久 turn/wakeup 后返回 202 与 turn_id。必要时增加版本化 endpoint，避免改变现有同步调用方的响应类型却不升级前端。

流式输出可以提供早期交互，但流不是事实源。断流、页面关闭不会取消服务端已受理轮次。读取接口能独立恢复完整状态。

waiting 时持久保存并退出作业。事件/用户决定/受控超时重新唤醒；补偿任务只扫描持久待办与租约，不把全量持续 polling 写入图节点。

### 9.6 在途迁移与回退

采用 additive schema 和 per-turn engine_version：

1. 部署新字段/表和兼容读取，默认仍路由现有引擎。
2. 部署新 Worker 并验证健康、隔离与空载恢复。
3. 对明确作用域的新 Turn 启用新引擎。
4. 旧 Turn 按原引擎排空，原文本请求不迁移到未知检查点。
5. 确认没有旧在途依赖后移除旧推进路径；保留必要历史读取。
6. 回退只改变之后新 Turn 的路由。已开始的新轮次暂停或由兼容的新引擎继续，不能交给旧逻辑猜测恢复。
7. 任何回退都保留已受理命令、产物和审计，不删库回退，不恢复被移除的 Legacy 产品。

生产隔离不依赖“先排空所有媒体任务”。媒体应按其已有身份继续；导演迁移只管理自己负责的轮次与关联。

## 10. D6：接回领域工具、用户决定和工作台

### 10.1 主链

- Story：从真实文本形成 typed Story Proposal，保留部分采纳/拒绝及版本冲突。
- Shot：读取有效创作意图和当前阶段；通过明确模型绑定形成建议，使用既有执行入口。
- Review/Repair：将批注与受影响 Artifact 作为引用，区分剪辑问题与素材重做。
- Editing：建议仅修改允许的剪辑草稿/时间线；不改 Shot Formal 或生产血缘。
- Export：仍是显式业务命令，冻结 Timeline；导演不得直接调用 FFmpeg 创建“正式成片”。

### 10.2 用户决定与授权

保持 Proposal、Apply、Save、Execute、Formal、Export 的区别。记录用户决定时绑定 Proposal 版本、应用范围与预期事实。已有决定重复提交幂等，不能反复应用。

AUTO 允许在有效授权范围内有限推进到下一确认点；ASSIST 主动建议，执行由用户触发；MANUAL 不自动续接。用户介入可停止新动作，但不抹除已在途生产。

撤销与受理必须按同一业务作用域进行并发校验。仅在 UI 隐藏按钮、仅在模型 system prompt 写“尊重用户”或仅监听模式变化事件均不构成 Gate。

### 10.3 上下文和拒绝记录

有效意图继续按用户已确认值、已采纳提案、项目覆盖、模板/Skill/风格默认排序。冻结必要版本/hash，与实际文本和媒体请求形成来源链。

摘要/压缩必须保留不可压缩的业务引用：用户明确禁止项、已拒绝提案及上下文指纹、锁定字段、授权范围、当前版本。SDK 自动记忆不得成为第二个产品事实来源。

不得默认加载开发目录的 Agent skills、shell 工具或机器级配置来充当导演创作能力。产品 Skill/风格仍由现有配置与 compiler 管理。

### 10.4 UI 改动

| 当前用户事实 | 目标显示/动作 |
|---|---|
| 导演已受理，尚在推理 | 导演处理中，可停止；生产状态不假报运行 |
| Proposal 等待决定 | 显示 diff、部分采纳/拒绝，保留现有保存语义 |
| 生产已受理，导演消费滞后 | 立即显示生产回执；导演状态等待同步 |
| 导演暂停，媒体仍运行 | 两侧状态分别显示，用户仍可查看/操作生产 |
| 用户改了设计 | 草稿保留；旧建议过期或待重新分析 |
| 网络断开后重连 | 读取服务端快照，不从本地消息猜测续跑 |
| 提案拒绝 | 持久显示拒绝结果，同一上下文不重复自动推荐 |
| 导出完成 | 当前与历史 MP4/SRT 可读；没有字幕时明确空状态 |

保留现有 Canvas-first、qc-* 组件体系、Query 和有界轮询。只为确认的状态语义问题修改 UI，不追加全局状态/CSS/组件库重构。

### 10.5 验收案例

1. 用户要求“白西装，不要推近”，最终 typed intent 与冻结请求保持一致，风格默认不覆盖。
2. 导演等待时用户改变 Formal，旧视频生产计划不得使用错误引用。
3. 用户部分采纳 Story/Editing Proposal，只有选中项改变，拒绝项保持不变。
4. 切到 MANUAL 后不发新自动生产，已受理任务继续如实显示。
5. 切镜头/重进页面，A 的草稿和建议不进入 B。
6. 关闭导演后手动完成关键帧、视频、Formal、Review、Editing 和导出。
7. 字幕/Timeline 改动重导出，图片/视频 ProviderOperation 增量为零。

## 11. D7：跨 Runtime 故障矩阵

### 11.1 核心矩阵

| ID | 故障/并发场景 | 必须断言 |
|---|---|---|
| F01 | 导演进程完全停止 | 手动生产受理、Formal 和 Export 成功，不等待导演 |
| F02 | 文本推理超时 | 只影响导演轮次；既有媒体任务状态不被篡改 |
| F03 | 模型已提交但无响应身份 | 记录 unknown_submission，不自动换模型/重发 |
| F04 | 文本结果落库后 crash | 原 invocation 复用，模型调用次数不增加 |
| F05 | 业务命令受理后 checkpoint 前 crash | 同 command_key 同 receipt，NodeRun/create 不增加 |
| F06 | 同一 resume 被两个 Worker 处理 | 单一有效推进者，动作及回复不重复 |
| F07 | 旧 Worker 租约过期后迟到返回 | 旧 epoch 不覆盖新 checkpoint，不下发新动作 |
| F08 | Outbox 发布后确认前退出 | 重投被 Inbox 去重，必要唤醒不丢 |
| F09 | Inbox 落库后队列故障 | 恢复后补发 wakeup，最终收敛 |
| F10 | 完成事件乱序/重复 | 不倒退状态，不把旧候选自动 Formal |
| F11 | 读取授权后立即撤销 | 受理 Gate 拒绝；若先受理，则显示真实在途 |
| F12 | 等待期间改设计/切 MANUAL | 旧上下文停止自动写入 |
| F13 | 生产已完成、导演未处理 | 读接口能够校准，零额外生成 |
| F14 | 远端媒体已有 task ID 后重启 | 恢复同远端任务，create 增量为零 |
| F15 | 用户停止导演、媒体迟到成功 | 记录候选，Formal 不自动改变 |
| F16 | 跨租户猜测 thread/execution ID | 读/恢复均拒绝，无 checkpoint 泄露 |
| F17 | 新旧引擎混合在途 | 同 Turn 不双跑；历史能读取，不猜造迁移状态 |
| F18 | 只改字幕/Timeline 再导出 | MP4/SRT 对应冻结版本，零图片/视频调用 |

### 11.2 分层验证

- **单元**：上下文编译、tool 白名单、模式/授权策略、Schema 修复和状态投影。
- **PostgreSQL**：receipt 唯一性、CAS/租约、Inbox/wakeup 原子性、RLS、迁移和事务隔离。
- **Redis/进程**：真实消息发布、独立消费、租约接管、进程退出后的持久唤醒。
- **模型 adapter**：真实通道契约与身份验证；控制流用测试模型，费用与效果按授权的真实调用验证。
- **前端/E2E**：状态拆分、dirty/stale、用户决定与离开重进。
- **FFmpeg**：冻结时间线、字幕、可播放交付及源媒体调用增量。
- **Golden**：在新候选上完成实际用户路径，不能用 mock 提案替代真实文本导演。

测试失败先定位具体风险，修复后跑受影响集；达到相应退出条件后停止可选扩测。最终完整 Gate 按仓库当前要求执行，不凭本文臆造命令或盲跑过时脚本。

### 11.3 证据字段

每项记录 source SHA、engine/package 版本、state schema、镜像/迁移身份、测试时间、场景输入 hash、turn/invocation/command/NodeRun/operation/Artifact 关联、注入时点、预期与实际、Provider create 增量。

保留失败与 NOT_RUN，不把超时、跳过或历史 PASS 改写为本轮成功。日志使用脱敏摘要，不导出凭据或不必要的完整模型上下文。

## 12. D8：双路径验收和新候选交付

### 12.1 两条主链

| 路径 | 必须覆盖 |
|---|---|
| 模板创建 + AUTO | 初始化同一 Project；真实导演提案；用户决定；授权范围内有限推进；候选/Formal；Review/Repair；Editing；MP4/SRT |
| 自由创建 + ASSIST | 自由输入、真实 Story/Shot/Editing 提案与部分采纳/拒绝；手动执行；同一生产内核和交付 |
| MANUAL 专项 | 导演服务停用时完整核心制作；无自动续接、无第二套生成路径 |

路径规模按实际剧本需要确定，不重新引入固定十镜或其它固定镜头数规则。真实验收优先复用已有项目事实和产物，仅在需要证明新调用链时产生最少必要新增调用。

跨供应商验证沿现有有效配置。如果原合同要求 Agnes + MiniMax，须在对应组合上提供证据或明确未验证，不硬编码进基础设施，不用另一组合偷换完成定义。

### 12.2 成片与增量证明

同时记录播放/下载、容器/编解码、真实时长、字幕时间与内容、产物 hash、ExportItem 血缘和冻结 Timeline 版本。字幕不存在时不伪造下载件。

对仅字幕或剪辑修改，比较前后源媒体 ProviderOperation/create 次数，不能只靠某个节点显示 cached 推断没有重新收费生成。

### 12.3 候选一致性

1. 冻结新 runtime source SHA 和锁文件，不使用 mutable dev 作为唯一证据标识。
2. 构建并记录 API、导演 Worker、生产 Worker、dispatcher、frontend 实际镜像身份。
3. 校验迁移 head、生成 API 合同、模型配置版本和部署命令。
4. 执行要求的静态、单测、PG、消息/恢复、前端、E2E、Golden 与 Release Gate。
5. 若代码/依赖/迁移变化，只重跑受影响证据并最终重新汇总候选。
6. 若只是增加证据/文档提交，记录 runtime source 与 evidence commit 的关系，证明运行输入未变化；不能把“文档提交不同 SHA”忽略不解释。
7. 更新既有任务索引和评审材料，使旧候选与新 Runtime 结果都可追溯。

原 PR #66 的状态只作为历史/当前登记参考；实际实施时重新读取，不假定仍未合并，也不把本次文档工作扩展成自动批准或合并。

### 12.4 完成状态

- D0–D8 实现/验证结束但仍需发布动作时，给出可审阅候选与真实状态。
- 只有当前任务所要求的发布/合并及后续身份核查都完成，才按仓库规则更新最终完成状态。
- 若新引擎硬门失败，维持现有可用候选，报告失败原因及受影响范围；不宣称新 Runtime 已上线。

## 13. 工期和 9 月 15 日目标

以下是工作量估算，不是实测工期。按一名熟悉代码的工程师、现有基础设施可用估计：

| 工作 | 估算 |
|---|---|
| D0–D1 基线/契约 | 0.5–1 人日 |
| D2 事务事件/持久唤醒 | 1–2 人日 |
| D3 文本职责拆分 | 0.5–1 人日 |
| D4 主选垂直切片/硬门初验 | 1–2 人日 |
| D5 执行隔离/检查点/迁移 | 1.5–2.5 人日 |
| D6 业务接入/交互 | 1–1.5 人日 |
| D7–D8 故障矩阵/候选验收 | 2–3 人日 |

合计约 7.5–13 人日，遇检查点权限、网关兼容或在途恢复问题需重新估算。Pi/Claude 备选薄适配验证是触发后的额外任务，不藏在上述主选估算里。

如果 9 月 15 日仍是交付目标，优先把 D1–D3 的边界修正与 D4 的有界验证做扎实，再由实际进度决定是否能完成新 Runtime 全链验收。原 V1 候选发布和新 Runtime 改造分别管理；不能在剩余日历时间不足时把未完成的新引擎写成既有发布条件已经满足。

可以延后：开放式多 Agent 协作、通用技能市场、复杂沙箱、长期记忆平台、全站 SSE 重构。不能延后到上线后再补：命令幂等、租户隔离、用户 Gate、持久等待、未知提交处理和在途单一推进者。

## 14. 实施过程中的明确禁区

- 不因为“要解耦”重建生产 Runtime、模板 Runtime 或独立 Agent 生成产物表。
- 不把所有异常统一自动重试三次。
- 不让同一 Turn 同时被旧 TurnService、LangGraph 和 reconcile cron 推进。
- 不用数据库里的轮次状态与 SDK 会话各自决定生产命令成功。
- 不让生产请求等待导演更新，也不用吞异常或内存 callback 代替可靠事件。
- 不把停止导演等同于取消所有远端媒体任务。
- 不用非 Claude 网关代理成功的偶然结果宣称 Claude SDK 支持通用跨模型替换。
- 不把 Pi 有会话能力写成“无恢复”，也不把它的会话等同于项目业务事务。
- 不以框架默认文件工具绕过 Proposal、Formal、Repair、Export 服务。
- 不复活 Legacy、旧 Budget/ProductionBatch、固定镜头数或 Quick/Professional 双产品。
- 不用旧候选的 Golden/Release PASS 为新运行代码背书。

## 15. Task Contract 模板

~~~markdown
# V1-Dx — 任务名称

## Authority
用户 2026-09-09 Runtime 修订、配套设计章节、既有七方案关联约束。

## Current evidence
固定基线、现有函数/表/接口、已完成 R 任务、确认耦合点。
区分源码事实、历史报告、本任务新实测和仍未验证事项。

## Outcome
一个可审阅的业务或技术结果，明确对用户行为的影响。

## Owned scope
现有路径、新增接口/迁移、测试范围、禁止变更对象。

## Transaction and state authority
每个写入的唯一拥有者、提交边界、重放策略、租约/版本条件。

## Implementation
按依赖顺序列出步骤，不把有副作用操作放到不受保护的重放点。

## Acceptance
具体场景、输入、故障注入、预期调用次数/血缘、通过与停止条件。

## Evidence and rollback
source/image/dependency/migration/engine 身份、实测记录、在途回退方案。
状态只能基于已取得证据更新。
~~~

## 16. 设计—实施—验收追踪

| 设计要求 | 实施任务 | 核心证据 |
|---|---|---|
| 两种 Runtime 独立、统一生产内核 | D1/D2/D5 | F01、架构依赖、单一 NodeRun/Artifact |
| transport 不再拥有流程 | D3 | invocation replay、无隐含业务 commit |
| 有界 Agent loop + 持久暂停 | D4/D5 | H1/H7/H9、跨进程确认点 |
| 回执防重复副作用 | D1/D2/D5/D7 | H2、F05/F06/F07 |
| 事件与持久唤醒 | D2/D7 | F08/F09/F10/F13 |
| 用户授权和版本优先 | D1/D6/D7 | H4、F11/F12 |
| SDK 可替换、业务契约稳定 | D1/D4 | 无 SDK 类型泄漏；ADR 与同组硬门 |
| 模型能力/身份保持 | D3/D4/D6 | H6、真实调用身份与意图来源 |
| 多租户检查点 | D5/D7 | H5、F16 |
| 新旧在途单一推进 | D5/D7 | F17、engine 路由与回退记录 |
| 创作交互及交付不退化 | D6/D7/D8 | 双路径、MANUAL、MP4/SRT、F18 |
| 新候选证据独立可信 | D0/D8 | source/image/evidence 映射与真实完成状态 |

## 17. 固定来源入口

- [dev 核查基线](https://github.com/zwb2002-yjy/dramaforge-p0/commit/4de7acd14481e262346fb0a4802d7725586194ed)
- [项目规则](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/AGENTS.md)
- [权威方案与用户修订入口](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/docs/plans/professional-program-v2/README.md)
- [当前 Goal/R 任务状态](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md)
- [生产事务耦合点](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/api/v1/workbench.py)
- [业务检查点](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/director/business_checkpoints.py)
- [文本 transport](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/director/text_transport.py)
- [NextAction](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/director/next_action.py)
- [Outbox](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/app/events/outbox.py)
- [后端依赖基线](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/backend/pyproject.toml)
- [已完成的 R6 字幕交付](https://github.com/zwb2002-yjy/dramaforge-p0/blob/4de7acd14481e262346fb0a4802d7725586194ed/docs/plans/professional-program-v2/task-contracts/V1-R6-FINAL-FILM-SUBTITLE-DELIVERY-20260908.md)

官方框架来源用于能力判断，不能替代本项目集成验证。所有新增目录、DTO、任务 D0–D8 和估算均为本次计划；只有实施后产生的具体证据才能改变其状态。
