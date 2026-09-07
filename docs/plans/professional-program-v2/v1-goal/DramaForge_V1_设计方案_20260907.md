# DramaForge V1 设计方案

**版本：2026-09-07，基于 dev 实码复核的修订稿**\
**配套文档：DramaForge_V1_实施方案_20260907_修订版.md**\
**核查基线：15a0b41338d51eeb2da162180869f45291fd5aef**\
**定位：既有 V1 Goal 的补充修订，保留统一创作主链及七方案未被覆盖的约束。**

## 1. 设计结论

DramaForge 已经具备真实的影视生产底座和较完整的创作工作台。当前应完成的是：**把真实导演推理、用户确认、镜头生产、审片修复、剪辑交付接成可恢复且用户能看懂的一条流程，并对最终候选重新验收。**

不应依据旧阻塞描述，再重建 Production Runtime、Worker、Final Film、Query 状态框架或模板系统。也不能因为这些模块存在、CI 通过，就宣布产品已完整可用。

本次设计集中解决五类问题：

1. **状态与证据不一致**：Goal 仍 BLOCKED，但部分列出的阻塞能力已有实现；需要按子项重新验收。
2. **导演能力与产品描述不一致**：当前主要建议入口默认是确定性规则，尚不能证明真实 LLM 导演闭环。
3. **用户工作流仍有断点**：Scene 异步状态更新、离开镜头时的草稿处理、候选到正式结果、等待与恢复需要整体验证。
4. **能力声明与实际生效之间需要证明**：模型能力、Skills、风格、连续性已有结构，但必须沿真实请求验证，而非继续增加空壳配置。
5. **交付证据没有覆盖当前工具链与源码**：当前 dev 的 CI/Security 通过，Release 被跳过，旧 Golden 不覆盖新候选。

## 2. 依据、时点与证据边界

### 2.1 本轮实际查阅

| 依据 | 本轮使用方式 | 限制 |
|---|---|---|
| 用户附件《DramaForge_V1实施方案_20260907.md》 | 全文读取；逐项纠正基线、缺口、路径和实施顺序 | 附件的勾选、工期和示例代码不是代码事实 |
| 《总结周末合并情况》对话 | 使用当前可见历史摘要；检索该标题及 Runtime 讨论 | 未检索到完整原始对话，不声称逐字承接或完整复原其中结论 |
| GitHub dev | 读取固定 SHA 的目录、核心源码、合同、PR、提交和 Actions 状态 | 没有运行用户本地应用、数据库或付费生成 |
| 仓库权威方案 | 阅读七方案索引及 V1 两份总方案、相关任务合同 | 未重新逐字审计七份原始长文；相关约束继续有效 |
| 历史 Golden/Release 报告 | 用于定位实现与历史候选 | 不迁移为当前候选 PASS |

本轮属于**设计与实施文档编制**，不包含应用代码修改、Goal 台账变更、部署、合并或新付费调用。执行阶段仍按当前任务范围及已存在的有效授权推进，不因本文件重新要求用户批准已经授权的工作。

### 2.2 当前 dev 与周末合并的准确关系

仓库：[zwb2002-yjy/dramaforge-p0](https://github.com/zwb2002-yjy/dramaforge-p0)。本次以固定 SHA 为证据基线，避免分支继续变化造成混淆。

| 提交 / PR | 内容与意义 |
|---|---|
| f7d84e1 | 恢复既有 EditSession 与冻结成片历史；修复实际审片播放、时间标注及上下文 Director 入口 |
| 6a269f2 | E2E 改为真实导航与“请求建议→预览→应用草稿→显式保存→重载”语义，替换过时固定建议断言 |
| PR #12 / 4cae136 | dev 合入 main 的集成与验收修复；不等价于后续 dev 全部内容已部署 |
| d024b2d | 统一 L1/L2 导航、项目大厅、独立设置入口、最近视图恢复和 Review 归属；是附件基线 |
| PR #65 / 15a0b413 | 将历史证据分支与 19 个依赖分支整合进 dev；含 Python/Node/TypeScript 等兼容修复 |
| b407469 | #65 的集成源头：锁文件、安全修复、原生 TypeScript 编译器与 API 版本共存、PackRegistry 语法适配 |

时间按用户常用 UTC+8 理解：PR #65 于 **2026-09-07 03:22** 合并，因此“周末合并情况”应区分 9 月 6 日晚的修复与 9 月 7 日凌晨的整合，不能全部写成周六完成。

从 d024b2d 到 15a0b413 的 GitHub compare 显示 **43 个可达提交、19 个变化文件**。43 包含被合入的分支历史，不代表新增 43 项产品能力。变化集中在依赖、镜像、Actions、历史证据和 PackRegistry 兼容，不是重做创作架构。

agent/dev-branch-integration-20260907 是整合工作分支，已通过 #65 进入 dev；无需再将它规划成新功能开发分支。是否清理其残留引用属于独立维护事项，不影响本设计。

### 2.3 当前质量状态

| 项目 | 核查结果 | 可得结论 |
|---|---|---|
| dev CI | success，run 34054711617 | 当前提交的 CI 工作流通过 |
| dev Security | success，run 34054711552 | 当前提交的安全工作流通过 |
| dev Release | skipped，run 34054711575 | 没有本次候选的 Release Gate 通过记录 |
| Goal 索引 | GOAL_BLOCKED；G7/G8 IN PROGRESS | 不能直接标记 GOAL_DONE |
| #65 任务证据 | 记录 900 后端单测、20 PG、5 proxy/mock；134 前端单测、17 E2E；审计为零漏洞 | 是该集成任务的记录，本轮没有亲自重跑 |
| 当前用户运行环境 | 未核实 | 不声称本地 8080、Worker、数据库与 dev 一致 |

**源码已有、自动化通过、真实环境可用、可发布是四种不同结论。**

## 3. 相对附件的修正

| 附件判断 / 建议 | 实码复核 | 本方案处理 |
|---|---|---|
| Final Film 真渲染未完成，从 delivery/final_film.py 新建 | production/final_film.py、timeline_renderer.py 已有排队、Worker 渲染、裁切、字幕、音轨、转场及成片持久化 | 复用；验证语义与当前候选证据，仅修复复现问题 |
| Worker 缺失完整执行，统一自动重试 3 次 | scheduler.py、workers/jobs.py 已分离排队与执行，包含恢复与错误分类 | 保留现有语义；按故障种类验证，禁止未知提交盲重试 |
| NodeRun 缺 cached，应新增 pending/completed 状态机 | execution/models.py 已有 queued/running/cached/completed 等状态 | 不创建第二套枚举，UI 做派生映射 |
| 前端没有进度和 dirty gate | ProductionMonitor、ShotProductionTrace、ShotProductionActions、EditingWorkspace 已有相关能力 | 补 Scene 刷新与流程衔接，不从零搭框架 |
| Agent Runtime = React Context + SSE | React 只能投影后端任务，不负责持久决策、权限、幂等和恢复 | 明确三层职责，见第 5–7 节 |
| SSE 使用 /events 或项目 events | 实际路由为 /api/v1/events/stream，hub 是进程内缓冲 | V1 优先有界轮询；不把现有 SSE 当成可靠跨进程完成事件总线 |
| partial apply 缺失 | ProposalService、Story apply、Shot/Editing 提案路径已有实现 | 分入口保留原有应用语义，补负向与恢复用例 |
| 没有 Skills、风格、连续性基础 | creative_capabilities 与 workflows/continuity 已存在 | 验证有效输入到请求快照的闭环 |
| 在 Provider Compiler 中临时查询前镜并拼接约束 | 会让执行输入随数据库变化，可能覆盖用户显式选择 | 在创意决策阶段形成可见且可确认的约束，执行时使用冻结结果 |
| 默认 Agnes 图片 + MiniMax 视频为唯一主链 | 历史 Golden 记录包含 Agnes 图像和视频；现有模型由 Profile/Binding 决定 | 区分“双创作路径”与“双供应商”；跨供应商验收单独列出 |
| Tailwind + Radix 是当前前端框架 | 当前 package.json 直接依赖没有这两项 | 延续现有 React/CSS 与 qc-* 体系，不为重设计换 UI 栈 |
| 按旧 release-gate-board.md 发布 | 该文件明确标记 HISTORICAL | 使用当前 G7/G8、Actions 和最终候选合同 |
| 默认 5–7 周、增加两张可选业务表 | 未基于当前完成度和复现结果估算 | 先验收再拆实际增量，保持 9 月 15 日首版目标的范围控制 |

## 4. 产品目标与范围

### 4.1 首版定义

**单用户可在本地服务中，通过正式 8080 入口及同源 API，完成一个可控、可恢复、可追踪的 AI 短剧 / 漫剧制作闭环。**

创作流程：

> 模板或自由创建 → 创意与剧本提案 → 场景 / 镜头设计 → 角色与参考素材 → 关键帧候选 / 正式关键帧 → 视频候选 / 正式视频 → 审片 / 局部修复 → 持久剪辑 → 成片交付。

保持两个正交维度：

| 维度 | 取值 | 作用 |
|---|---|---|
| 创作起点 | Template / Free | 初始化内容与创作偏好 |
| 导演参与度 | AUTO / ASSIST / MANUAL | 影响建议、推进及信息密度 |
| 共同生产事实 | Project / Scene / Shot / GraphVersion / NodeRun / Artifact / EditSession | 所有组合共用 |

模板数量、镜头数量由内容决定；三镜 Golden 只是测试样本，不成为产品固定镜头数。

### 4.2 首版必须保留

- 用户可拒绝、修改和部分采纳导演建议，后续生成必须以最终保存的选择为准。
- 用户能完全手动走完生产链；关闭导演不会关闭产品。
- Candidate 预览不写正式事实；Formal 必须明确确认并带版本守卫。
- 编辑修改与媒体重生成分开；只改字幕或剪辑不重新请求图片/视频。
- 保留资产版本、血缘、跨项目隔离、模型身份和幂等保护。
- 提供能播放与下载的最终 MP4；以本次修订明确补齐与最终 Timeline 对齐的独立 SRT 交付。
- 模型槽位只配置一个有效模型时仍能使用；不要求用户为每个槽位配置多个备选。
- 保留已有费用/定价来源记录，不新建账单系统，也不删除执行溯源。

### 4.3 本轮不扩展

不建立通用多 Agent 平台、模板市场、复杂三维、团队协作、复杂资产状态时间线、账单后台、剪映逆向导出或 ComfyUI 编排。已存在的相关模块不因“不扩展”而被随意删除。

既有检查与 Review/Repair 保留；不新建人脸 embedding 或外部视觉质检产品，也不将当前元数据、规则检查宣传成完整视觉质量保证。

## 5. 架构：三层 Runtime 的职责

| 层 | 所负责的事实 | 现状 | 本轮设计 |
|---|---|---|---|
| Director 决策层 | 用户目标、上下文、建议、确认点、下一步动作 | Thread/Message/Proposal、规则建议及策略存在；完整真实推理与持久推进未被证明 | 复用提案机制，补真实文本适配及有界决策轮次 |
| Production Runtime | 已确认生产命令、执行身份、排队、重试、恢复、产物 | 已实现 | 保持唯一，按明确失败场景补强 |
| 前端状态投影 | 当前选中、草稿、预览、服务端任务与错误显示 | 已实现多个局部能力 | 收敛读取与等待，不持有第二套执行事实 |

另有“开发 Agent Goal 运行协议”，它指导 Codex 如何连续开发和验收，**不是产品内导演的运行时**。不得把“读取任务合同→编码→测试→提交”当作影视导演与用户交互的实现。

~~~mermaid
flowchart TD
    U["用户目标与修改"] --> D["导演决策与提案"]
    F["项目与创作事实"] --> D
    D --> G{"需要确认？"}
    G -->|"是"| U
    G -->|"已满足授权与版本条件"| C["现有业务命令"]
    C --> P["统一 Production Runtime"]
    P --> A["候选产物与执行结果"]
    A --> F
    F --> V["Canvas 与剪辑视图"]
    A --> D
~~~

生产层继续使用现有 GraphVersion / NodeRun / Outbox / Arq / Worker / ProviderOperation / Artifact。导演层只能通过已有业务服务提交命令，不能绕过它们直接调用图片或视频 Provider。

## 6. 导演决策层设计

### 6.1 先补真实推理，不把规则模板当成大模型能力

当前发现：

- suggestion.py 的默认 Shot transport 是 DeterministicShotDirectorSuggestionTransport。
- recommendation.py 默认 DeterministicDirectorRecommendationTransport。
- editing_suggestion.py 默认 DeterministicEditingDirectorSuggestionTransport。
- story_proposal.py 将用户提供的 draft_text 解析为 typed diff；该函数本身不从创意生成剧本。
- autonomy_policy.py 中 AUTO 和 ASSIST 当前布尔策略相同。枚举与开关存在，不证明两者已形成不同的持续推进体验。

目标增加**明确配置的真实文本模型 transport**，复用 TextGenerateRequest、LiteLLMModelAdapter 及现有模型槽位体系。Story 使用 planning.script；分镜/Shot 建议使用 planning.storyboard；brief 分析使用 planning.brief。剪辑建议的槽位映射在任务合同中显式登记，V1 优先复用现有文本槽位，不暗造不可配置的“导演默认模型”。

默认生产路径在无可用文本绑定时给出“模型未配置 / 本次建议失败”，仍允许手动制作。确定性实现保留为测试夹具或明确标注的规则建议，**不得在真实模型失败后静默伪装为 AI 成功**。

文本 Adapter 已存在，不代表 Director 的业务入口已经接通。新增桥接必须同时补上真实调用记录和输出校验，不能只有一个直接 HTTP 调用。

### 6.2 一次决策轮次的输入

冻结以下信息并计算上下文指纹：

| 类别 | 必须包含 |
|---|---|
| 身份与作用域 | workspace、project、scene/shot 或 edit_session、actor |
| 创作事实 | 已保存的剧本/镜头设计、版本、Formal 引用、锁定字段 |
| 用户意图 | 当前请求、明确接受与拒绝的决定、禁止改变的要点 |
| 创作配置 | 模板/Skill/风格/镜头语言的版本与 hash、项目覆盖值 |
| 可执行能力 | 有效模型 Profile/Binding 及能力摘要，不含凭据 |
| 生产与剪辑状态 | 有效最新 NodeRun、候选、Review 注释、Timeline 版本 |
| 控制边界 | autonomy、当前授权范围、最大动作次数、停止条件 |

用户尚未保存的前端草稿不能冒充服务端事实。若用户希望针对草稿请求建议，应以明确“草稿预览”输入提交并标注基准；应用前仍校验服务端版本及当前草稿指纹。

AssistantContextBuilder 当前有一个应重点验证的范围问题：shot scope 先按 shot ID 查询 Scene，可能不能正确获得该 Shot 所属 Scene。按 shot.scene_id 加载的修正，应以复现测试确认后实施。

### 6.3 输出契约

一轮只产出一个有限、可校验的结果：

- 当前理解：简短说明采纳了哪些用户要求。
- 建议差异：旧值、新值、理由、影响对象、风险。
- 来源：模型身份、上下文指纹、Skill/风格版本、相关事实版本。
- typed operations：仅允许已有白名单业务指令。
- 下一步：等待用户、等待生产、继续分析、已完成、受阻。
- 停止原因：缺事实、版本变化、未授权、模型失败、能力不支持等。

禁止输出 SQL、任意代码、Provider 凭据、可直接执行的任意 URL、伪造 Artifact/NodeRun 或自由格式执行命令。模型返回的结构一律视为未验证提案。

### 6.4 用户修改必须真实生效

优先级固定：

> 用户显式且已确认的值 ＞ 已采纳提案 ＞ 项目覆盖值 ＞ 模板 / Skill / 风格默认值。

实施时使用一个归一化的 effective creative intent 作为后续编译输入；不能只在注释中声明顺序而实际遗漏 accepted proposal 或锁定字段。

例如用户要求“角色穿白西装，镜头不要推近”，导演不能在可见提案中同意后，后台又加“黑衣、dolly in”。若风格包与用户要求冲突，保留用户值并在来源解释中记录被覆盖的默认值。

与前镜的连续性推断不能自动升级为事实。场景时间跳跃、明确换装、新道具或用户禁用约束，应能覆盖继承。所有新增约束先进入可见差异，再在确认后的设计快照中冻结。

### 6.5 持久轮次与推进

**新增建议：DirectorTurn 决策记录**，这是本次修订的设计项，不是当前已存在的表。它只记录导演轮次和业务关联，不复制 Graph/Artifact，也不恢复已删除的旧 AgentRun/Budget 体系。

最小字段：

| 字段组 | 语义 |
|---|---|
| id / scope / actor | 项目内轮次身份与所有者 |
| request_key / context_hash | 请求及上下文去重 |
| input_versions / intent_snapshot | 当时依据的事实和用户要求 |
| model_resolution / transport_record_id | 文本调用的实际身份与记录引用 |
| status / wait_reason / revision | 轮次状态及乐观锁 |
| proposal_id / dispatched_command_key / node_run_ids | 指向既有提案和生产事实 |
| step_count / deadline / last_error | 有界推进与错误记录 |

候选状态：queued、thinking、awaiting_user、awaiting_execution、completed、failed、cancelled、stale。它们是**导演轮次状态**，不替换 NodeRun 的现有枚举。

处理规则：

1. 用数据库唯一键和原子 claim 防止多次刷新或多 Worker 重复推进。
2. 文本调用在已有 Worker/任务基础设施中执行；异步入口只验证、冻结、入队。
3. 结果写入前重新校验版本；已被用户修改的上下文只能形成 stale 结果，不得覆盖新设计。
4. 提案生成、提案应用、设计保存、媒体生产是不同动作，分别记录。
5. 生产完成后重新读取事实，最多推进到下一个确认点；不靠浏览器保持页面打开。
6. 已拒绝建议在同一上下文下不自动反复生成；相关事实改变或用户明确重提才重新分析。
7. 每轮限制推理、结构修复和动作数量；出现未明原因不无限循环。
8. 写下发意图与 outbox 时使用同一事务；消费者使用稳定命令 key，并能在崩溃后查询关联业务事实，防止“已发命令、未记回执”导致重复生产。

文本调用若不能复用已有可执行的通用记录路径，应建立最小文本调用桥接，仍保留模型解析、脱敏请求摘要、实际结果、错误和计费事实。不得把旧 generation_service 的“Agent API”注释当作仍然存在的业务能力；也不得为复用而构造假的 Shot 或 Formal 产物。

### 6.6 AUTO / ASSIST / MANUAL

| 行为 | AUTO | ASSIST | MANUAL |
|---|---|---|---|
| 基于相关事实变化主动分析 | 是，去重且有次数限制 | 是，展示建议 | 否，用户请求才运行 |
| 生成提案 | 可以 | 可以 | 用户请求 |
| 应用 Story / 镜头 / 剪辑变更 | 按已有明确确认 Gate | 用户确认 | 用户操作 |
| 发起付费媒体生产 | 仅有效授权涵盖的对象、次数、模型及动作 | 用户显式触发 | 用户显式触发 |
| Candidate → Formal | 用户确认 | 用户确认 | 用户确认 |
| 最终成片导出 | 用户确认 | 用户确认 | 用户确认 |
| 生产完成后的下一步 | 自动读状态，推进到下一确认点 | 推荐下一步 | 展示结果 |
| 用户介入或切 MANUAL | 停止新的自动动作；在途任务继续按实际结果处理 | 同左 | 无自动续接 |

V1 的 AUTO 是**有确认点的有限推进**。不承诺自主审美评审、无限重做或无人值守全片生产。授权过期、模型/范围变化要重新计算 Gate；已有授权不应被每次刷新重复询问。

## 7. Production Runtime 设计与验证重点

### 7.1 已有职责不动

- API 创建业务执行计划，校验引用、版本与模型适配。
- NodeRunScheduler 负责 Outbox 与 Arq 入队，不执行 Adapter。
- Worker 执行实际媒体任务；ProviderOperation 保存执行身份与恢复上下文。
- 成功产物进入候选；Formal 由既有确认接口改变。
- Final Film 使用冻结 EditSession Timeline，生成新的 Export/Artifact。

### 7.2 重试不是“所有异常自动重试三次”

| 场景 | 目标语义 |
|---|---|
| 请求尚未提交、入队失败 | 明确失败并可恢复，不伪装排队成功 |
| 远端已返回任务 ID，Worker 重启 | 恢复查询同一远端任务，不重新 POST |
| 提交开始但没有收到任务 ID | 标记 unknown_submission，核对后再处理；禁止盲重发 |
| Provider 返回可重试限流 | 尊重分类与 Retry-After，保持身份及尝试记录 |
| 用户明确重做镜头 | 新尝试关联旧尝试，不能覆盖原产物 |
| Final Film 失败后重试 | 同外部 key、同请求允许下一 attempt；同 key 不同 Timeline 拒绝 |
| 用户取消后远端迟到完成 | 如实记录迟到结果；不能自动成为 Formal |

增量更新用**调用次数和输入血缘**证明：改字幕不应增加图片/视频 ProviderOperation；不能只断言某节点状态变为 cached 就宣布正确。

### 7.3 模型能力闭环

复用：ModelSlot → 有效 Profile → Binding / Catalog / Connection → Eligibility → ExecutionPlan → Compiler → ProviderRuntime。

要求：

- 没有单次覆盖时，正常使用项目或工作区配置解析；配置继承与失败后偷偷换模型是两回事。
- 指定模型/Binding 不可用时明确拒绝，不自动切换。
- 模型支持的时长、比例、分辨率、参考图/首尾帧和互斥约束以具体 Catalog/Binding 版本为准。
- UI 显示最终所选模型及适配结论；细节按需展开，不要求用户理解内部 ID。
- approximate 必须明确展示并确认；unsupported 在付费调用前失败。
- 预览到执行冻结 plan_fingerprint、具体引用与版本；恢复不得重新选择模型。
- 记录 accepted intent、语义 EffectiveRequest 和脱敏 native request 摘要之间的差异。

Agnes + MiniMax 是一个明确的跨供应商验证组合，不是基础设施硬编码。是否能测由该 Workspace 的有效配置决定；没有对应绑定就报告该组合未验证，不能拿其他供应商结果替代。

## 8. Skills、风格与连续性

已有 creative_templates、skill_library、packs、shot_language、creative_compiler 与 continuity 模块应保留。重点验证四件事：

1. **选中**：创建页或当前项目确实保存了用户选项。
2. **编译**：选项影响结构化创作意图，而非只有版本标签。
3. **执行**：对应内容进入实际冻结请求，未被后续默认 prompt 覆盖。
4. **解释**：用户能够看到来源并修改或禁用约束。

CreativeCapabilityCompiler 当前可以输出 story guidance、visual bible、workflow/quality hints 和 provenance；其返回路径未设置 shot_director_intent_patch。需连同 composer 与 shot_language_compiler 的调用路径验证，不能仅凭这个函数就宣布全部镜头语言失效，也不能只凭 provenance 就宣布全部生效。

连续性首版以角色/参考图、服装文本、场景设计和已确认约束为主。复用 SceneContinuityContext 冻结和已有状态字段；不新增泛化资产时间线表。

## 9. 工作台与交互设计

### 9.1 保留当前 Canvas-first 方向

当前 SceneWorkspace 已是单列 Canvas、Context Dock、按需浮动面板、候选区与紧凑 ShotStrip。新版在此基础上完善，不退回永久右侧大表单与多卡片后台。

视觉要求：

- 媒体占主要空间；背景和容器降低存在感。
- 延续现有产品色与 CSS，不引入通用暗紫渐变、装饰性数据卡或新组件库。
- 当前阶段一个主动作；次要动作放在菜单或上下文面板。
- Director 与 Details 按需打开，技术信息不挤占创作画布。
- 复用现有 qc-* 命名和组件，保持统一导航。
- 不先做全量 CSS 或全局 Zustand 重构。

### 9.2 阶段、主动作与状态

| 当前事实 | 主动作 | 页面反馈 |
|---|---|---|
| 无镜头设计 | 编辑设计 / 请求导演建议 | 明确缺少什么 |
| 本地未保存 | 保存设计 | 未保存提示；生成与过期提案应用禁用 |
| 可生成关键帧 | 生成关键帧 | 模型、参考就绪、必要适配确认 |
| 已提交 / 运行中 | 查看进度 | 当前步骤与等待原因；不是“提交成功=制作完成” |
| 有关键帧候选 | 预览 / 确认为正式 | 预览零写入；明确正式标识 |
| 正式关键帧就绪 | 生成视频 | 只引用已确认关键帧 |
| 有视频候选 | 预览 / 确认正式视频 | 继续保留旧 Formal，直到确认 |
| 正式视频就绪 | 审片 / 进入剪辑 | 时间标注、修复入口 |
| 失败 | 查看原因 / 允许时重试 | 区分可重试、需配置、需核对 |
| 剪辑已保存 | 生成成片 | 排队、渲染、完成可播放下载 |

候选预览和 Formal 默认展示语义必须保留；切换镜头时不把 A 的草稿、参考、建议带到 B。

### 9.3 状态读取与恢复

V1 默认采用现有 Query 体系补齐**有界轮询**：

- Scene 有 queued/running 等有效任务时轮询聚合读模型；终态停止。
- Production 页面已有 4 秒刷新，继续复用 latestEffectiveNodeRuns 的语义。
- Editing 已有等待和成片历史轮询，先修复中断重进、终态和超时表达。
- Query 负责服务端事实；React 局部状态或既有 Zustand 负责面板、选中和草稿。
- 网络中断显示“连接中断 / 状态待同步”，不把远端任务改为失败。
- 重连以完整快照校准，不能只等一个可能丢失的完成事件。

当前 SSE 路由与进程内 hub 并不自动构成 Worker→API 的可靠跨进程桥接。只有实际证实延迟或轮询负担需要优化，再单独补持久事件桥接、鉴权、重放和断流测试；不能将本轮交付依赖于先建设 SSE 平台。

### 9.4 草稿安全与导演面板

关闭 Context Sheet 保留当前镜头草稿。切 Shot、切 Scene 或离开编辑页时，若 dirty，明确选择保存或放弃，不能直接清空；保存失败保持草稿。

导演面板默认呈现：当前理解、一个重点建议、差异、原因、采纳/编辑/拒绝。允许 A/B 方案，但不一开始铺满长文本。用户修改后，旧提案立即标记过期；不抢焦点、不覆盖输入、不在后台重新套用旧方案。

既有入口语义不同，应保留：

- Story：逐项确认后由 ProposalCommandRegistry 写入规范 Story 事实。
- Shot：应用到本地设计草稿，显式 Save 才写入。
- Editing：提案预览、应用与持久保存沿当前版本化 API；不自动保存，不改生产事实。

## 10. 剪辑与最终交付

### 10.1 冻结 Timeline 才是成片输入

复用 production/final_film.py 与 timeline_renderer.py。成片必须反映：

- clip 顺序、source in/out、timeline duration；
- 用户保存的字幕与字幕开关；
- 选择的音轨、静音、可选音乐与音量；
- 当前支持且已验证的转场；
- 当时的 Formal Artifact 和 EditSession 版本。

渲染期间用户修改 Timeline，应产生下一版本；在途任务仍渲染原冻结版本，不能混入新编辑。

### 10.2 MP4 与 SRT

现有 render_timeline 返回 MP4；其内部按片段生成字幕用于渲染。production product_path 的 subtitle 节点还存在固定两秒 cue 生成逻辑。**镜头级 SRT 产物存在，不等于最终成片级 SRT 正确交付。**

本次补齐的最终 SRT 必须来自同一冻结 Timeline：

- 按裁切与重排后的时间计算 cue；
- 有转场时使用渲染采用的实际累计起点，不简单累加原片长度；
- 保留字幕关闭/空文本语义，处理换行及毫秒舍入；
- 以同一 Export 下的独立产物可下载，并记录 hash 和 Timeline 版本；
- 无字幕项目返回明确“无字幕内容”，不制造空的成功交付。

不靠从 Shot dialogue 重新推导覆盖用户在剪辑里改过的字幕。

### 10.3 验证必须使用真正的渲染

timeline_renderer 在 app_env=test 时走 _test_render。相应单测能证明结构和契约，但不能单独证明 FFmpeg 真实输出。

最终 Gate 使用生产形态镜像执行实际 FFmpeg，验证 MP4 解码、时长、裁切、字幕、音轨和下载；至少一个案例让 Timeline 与原始镜头顺序不同，避免“直接拼接也能过”的假阳性。

## 11. 数据与 API 边界

- 既有 Project/Scene/Shot/Artifact/EditSession/Export 身份不复制。
- 仅为明确新能力增加最小字段或 DirectorTurn；迁移编号由当前实际 head 决定，不能预占附件中的 0056/0057。
- 新异步导演入口可以返回 202 与轮次 ID；路径和 Schema 在实施任务中登记为新增，不伪称现有。
- 只读查询不能触发生成、恢复提交、自动 Formal 或渲染。
- 所有修改保留 actor、workspace/project 作用域、CSRF 与版本检查。
- 执行前端 API 由后端 Schema 生成，不手写漂移类型。
- 错误返回动作建议和稳定 code；不向用户暴露密钥、长 traceback 或原始敏感请求。

现有模型记录在失败后也要留存；删除旧兼容逻辑不意味着删除血缘、安全隔离或错误事实。

## 12. 首版部署与可用性

沿用现有 Compose：PostgreSQL、Redis、MinIO、LiteLLM 及其数据库、迁移、API、dispatcher、两类 Worker、前端 Nginx。默认只有前端网关发布宿主端口 8080，API 经同源代理访问；5173 保留开发便利用途。

执行验收分别记录：

- 源码 SHA、应用镜像 digest / OCI revision；
- API、dispatcher、Worker、前端是否来自同一候选；
- DB migration head 与应用角色权限；
- 文本、图像、视频、声音分别使用的实际模型；
- 一个用户的并发上限与轮询行为。

按用户“本地部署、先给单用户开放 API”目标实施。远程访问策略沿现有配置显式设置；不把数据库/Redis/MinIO 管理端口一并公开。

旧方案的 P95<500ms、成功率>90%、首屏<3s 没有测量基线。先记录可复现测量，发现真实卡顿再优化，不用这几个孤立数字替代主链验收。

## 13. 验收分层与完成定义

| 验收层 | 必须证明 |
|---|---|
| 代码契约 | 版本、幂等、身份冻结、跨项目、typed operations 正确 |
| 工作台体验 | 正式 8080 入口可走通、状态自动更新、草稿不丢、候选预览零写 |
| 真实导演 | 配置文本模型产生与上下文相关的建议；用户修改后实际请求保持一致 |
| 真实生产 | 对象存储、Arq、Worker、远端任务恢复及候选/正式链可追溯 |
| 真正交付 | 冻结 Timeline 渲染 MP4，字幕/音轨一致，SRT 可下载 |
| 候选发布 | 同一冻结候选的 CI、Security、Release、Golden、镜像、迁移和文件证据可关联 |

Template+AUTO 与 Free+ASSIST 是双创作路径；同一供应商完全可以承担两条路径。Agnes+MiniMax 是跨供应商组合，单列能力 Gate，不能混淆两种“双路径”。

本轮不把当前 GOAL_BLOCKED 直接解释为全部功能缺失，也不修改为 DONE。由配套实施方案逐项核验，只有最终候选证据满足 Gate 才更新状态。

## 14. 与既有权威计划的衔接

本文件由用户请求编制，是用于登记的 V1 Owner amendment 文稿。建议实施时在 professional-program-v2/README.md 的 Owner amendments 中登记两份修订文档，保留七份原文及 source-integrity。

本次明确修订：

- 将附件的重建任务改为按现状补全。
- 将“前端 Agent Runtime”改为导演决策层、生产运行时、前端投影三层。
- 增加真实文本模型导演和有限推进的可验收范围。
- 将最终 SRT 对齐冻结 Timeline 列入交付要求。
- 更新当前候选及证据来源。

本次不覆盖：Canonical 单一事实、执行身份冻结、禁止静默换模型、显式 Apply/Save/Formal/Export、权限隔离、旧双轨清理等既有原则。

不把开发任务重新展开成第二套 Professional Phase，也不恢复已废弃 Quick/Professional 两个产品。任务通过现有 G4/G6/G7/G8 的补充合同落地；已有 COMPLETE 只表示该历史合同完成，新增要求按新的补充合同验收。

## 15. 固定版本证据索引

以下链接均对应本次核查 SHA，代码存在性及行为判断可据此复核：

- [当前 dev 提交](https://github.com/zwb2002-yjy/dramaforge-p0/commit/15a0b41338d51eeb2da162180869f45291fd5aef)
- [PR #65 整合范围与记录](https://github.com/zwb2002-yjy/dramaforge-p0/pull/65)
- [附件基线至当前基线差异](https://github.com/zwb2002-yjy/dramaforge-p0/compare/d024b2d2ee23ea6e31ad08b99bbb2403a59fdbaf...15a0b41338d51eeb2da162180869f45291fd5aef)
- [CI 34054711617](https://github.com/zwb2002-yjy/dramaforge-p0/actions/runs/34054711617)、[Security 34054711552](https://github.com/zwb2002-yjy/dramaforge-p0/actions/runs/34054711552)、[Release 34054711575](https://github.com/zwb2002-yjy/dramaforge-p0/actions/runs/34054711575)
- [权威计划与 amendments](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/docs/plans/professional-program-v2/README.md)
- [Goal 状态](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md)
- [G7E 合同](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/docs/plans/professional-program-v2/task-contracts/V1-G7E-FINAL-FILM-ASYNC-TIMELINE-20260903.md)、[G8 合同](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md)
- [Final Film 服务](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/production/final_film.py)、[Timeline renderer](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/production/timeline_renderer.py)
- [Scheduler](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/runtime/scheduler.py)、[Worker jobs](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/workers/jobs.py)、[媒体执行](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/execution/product_path.py)
- [Shot 建议](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/director/suggestion.py)、[主动推荐](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/director/recommendation.py)、[剪辑建议](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/director/editing_suggestion.py)、[Story 提案](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/director/story_proposal.py)
- [创意 Compiler](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/director/creative_capabilities/creative_compiler.py)、[Autonomy](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/director/autonomy_policy.py)
- [SceneWorkspace](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/frontend/src/features/scenes/SceneWorkspace.tsx)、[EditingWorkspace](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/frontend/src/features/editing/EditingWorkspace.tsx)
- [SSE 进程内 hub](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/events/sse.py)、[实际 SSE 路由](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/app/api/v1/events.py)
