# DramaForge V1 实施方案（修订版）

**日期：2026-09-07**\
**配套设计：DramaForge_V1_设计方案_20260907.md**\
**核查基线：dev@15a0b41338d51eeb2da162180869f45291fd5aef**\
**适用：既有 V1 Goal 的补全、真实验收与发布候选收口。**\
**本文件交付状态：方案已编制；以下开发、运行验证及发布任务尚未由本轮执行。**

## 1. 执行结论

执行次序是：**校准现状 → 补实际工作流断点 → 补真实导演与有限推进 → 验证模型/创作输入 → 完成交付 → 同候选验收。**

不按附件重新编写 Runtime、Worker、Final Film，也不把“建一个 React AgentRuntimeProvider”作为 P0。当前应优先证明已有生产主链在新工具链上有效，同时修复已定位的 Scene 更新、草稿安全与真实导演接入缺口。

任务编号 R0–R8 是本次修订的工作索引，不建立新的主计划。每项须挂到既有 G4/G6/G7/G8 或相关 UI 合同的补充合同；不修改七份原始方案的正文与来源 hash。

## 2. 已核查基线与未完成证明

### 2.1 可以复用的事实

- dev 最新核查 SHA 是 15a0b413；附件 d024b2d 已不是最新。
- #65 已合入依赖与历史证据，不能将历史 Golden 转成当前 PASS。
- 当前 dev CI 和 Security 为 success，Release 为 skipped。
- production/final_film.py 已存在异步排队、冻结 Timeline、attempt 计算和 Worker 执行。
- timeline_renderer.py 已实现实际 FFmpeg 路径，但 app_env=test 会走测试替身。
- EditingWorkspace 已有 dirty gate、等待和成片历史轮询。
- SceneWorkspace 已有 Canvas-first 布局与 Query，但其自身查询未配置 refetchInterval。
- Production 页面已有 4 秒轮询和有效最新尝试聚合。
- Shot/Editing 建议默认确定性 transport；Story 提案接口需要 draft_text。
- 模型解析、Eligibility、Compiler、ProviderRuntime、恢复、Skills/风格/连续性模块已存在。

### 2.2 本轮不能替用户确认的事实

没有现场运行用户本地 Docker、数据库、真实 Provider 或浏览器流程。因此以下仍必须实证：当前应用源码/镜像是否一致、迁移是否一致、跨进程恢复是否有效、真实 LLM 是否通过业务入口调用、最终音画字幕是否正确、当前候选是否可发布。

指定《总结周末合并情况》对话的完整正文未检索到；本方案使用可见历史摘要和实际 GitHub 证据，不假装已完整阅读该对话。未来获得正文时，仅登记有明确影响的决定差异，不推翻已经核实的代码事实。

## 3. 工作包、依赖和产出

| 任务 | 主要产出 | 依赖 | 映射原合同 | 性质 |
|---|---|---|---|---|
| R0 基线与验收矩阵 | 逐项差异、现有 Gate 证据、当前运行身份 | 无 | G0 / G7E / G8 | 复核 |
| R1 工作台等待与草稿安全 | Scene 自动更新、离开保护、阶段主动作 | R0 | G5 / UI-1 / G7A | 局部补全 |
| R2 真实文本导演 | Story/Shot/Editing 文本 transport、调用记录、输出校验 | R0 | G1 / G4 / G6 补充 | 必要新增 |
| R3 创作意图与模型适配 | 用户选择、Skill/风格、约束和实际请求一致 | R2 的上下文契约 | G4 / Model Supply 补充 | 核验后修复 |
| R4 有限导演推进 | 持久轮次、去重、确认点、等待与恢复 | R1、R2、R3 | G3 / G4 / G6 补充 | 必要新增 |
| R5 执行恢复与重试验收 | 故障矩阵、重复请求保护、缺陷补丁 | R0；最终再覆盖 R4 | G7E / Runtime 既有合同 | 证明优先 |
| R6 成片与字幕交付 | 冻结 Timeline 真渲染验收、最终 SRT | R0；复用 R5 语义 | G7D / G7E | 局部补全 |
| R7 双创作路径与真实体验 | 真实导演+真实媒体+编辑交付证据 | R1–R6 | G7A / G7B / G7D | 验收 |
| R8 发布候选收口 | 同 SHA 的镜像、迁移、Golden 与发布门禁 | R7 | G8 | 发布准备 |

建议单执行者顺序：R0 → R1 → R2 → R3 → R4 → R5 → R6 → R7 → R8。R0 若复现“完全无法生成/无法导出”的 P0，应先将相应 R5/R6 缺陷拆成一个明确子任务修复，再返回此序列。

一个任务可以拆成多个小 PR，但每个 PR 只解决一个可验收结果。不要把依赖升级、全局 UI 重构和运行时改动混在一个大 PR。

## 4. R0：基线校准与证据重算

### 目标

区分历史阻塞描述、已有实现、实际缺陷、证据缺失。后续所有编码都基于这张差异表，不按旧文档的“未完成”直接重写。

### 必读路径

- docs/plans/professional-program-v2/README.md
- docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md
- docs/plans/professional-program-v2/task-contracts/V1-G7E-FINAL-FILM-ASYNC-TIMELINE-20260903.md
- docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md
- docs/plans/professional-program-v2/task-contracts/DEV-BRANCH-INTEGRATION-20260907.md
- .github/workflows/ci.yml、security.yml、release.yml
- docker-compose.yml、backend/Dockerfile、frontend/Dockerfile
- AGENTS.md；进入实际实现后再按需读取 agent.md / AGENT_EXECUTION_PROTOCOL.md

### 步骤

1. 重新读取远端 dev SHA，比较与 15a0b413 的差异。若前进，只审查影响本方案的增量。
2. 查看工作区 dirty 状态；隔离工作，不覆盖既有用户修改。
3. 登记两份修订文档为 Owner amendment，保留旧方案原文和 hash。
4. 检查当前候选 Actions；成功状态按 SHA 记录，不重复跑已经充分覆盖且未变化的同候选测试。
5. 在隔离候选环境核对 API、前端、dispatcher、两类 Worker 的源码/镜像身份与 DB migration。
6. 选择已有真实项目检查“打开→已有候选→正式结果→编辑历史→成片播放”，这一步原则上复用产物，不先触发新付费生成。
7. 将 G7E 的五项逐项拆成：代码位置、自动化证据、现场结果、剩余问题、负责任务。
8. 对不能核实的项写 NOT_VERIFIED；只对实际复现缺陷写 FAIL。

### 输出和验收

新增建议报告：docs/reviews/V1-RECONCILIATION-20260907.md。明确为本次拟新增文件，不是现有仓库事实。

通过条件：每个“缺口”都有具体行为与证据；全局状态仍遵守 G7/G8，不提前改 DONE。若代码已满足，则记“实现复用，待最终候选验收”，不删除保护逻辑，也不新建重复模块。

**工期参考：0.5–1 个有效工作日，取决于运行环境是否漂移。**

## 5. R1：Scene 等待、草稿和阶段操作

### 当前证据

SceneWorkspace 的 Query 当前只有 queryKey/queryFn/enabled，生成后由 ShotProductionActions invalidation/refetch。一次入队后的 refetch 不保证能看到若干分钟后的任务完成。

SceneWorkspace 在切选中 Shot 时清空 designDirty/suggestionDraft；是否丢失其他子组件草稿需用真实导航测试验证。已有 dirty gate 应扩展场景，不重建。

### 改动范围

| 现有文件 | 具体处理 |
|---|---|
| frontend/src/features/scenes/SceneWorkspace.tsx | 活跃任务时轮询聚合读模型；切换前 dirty 判断；保留当前草稿 |
| frontend/src/features/shots/ShotProductionActions.tsx | 区分请求提交与服务端执行；按当前阶段显示主动作；任务运行时避免重复提交 |
| frontend/src/features/shots/ShotDesignPanel.tsx | 保存失败保留草稿，暴露必要的保存/丢弃回调 |
| frontend/src/features/production/effectiveRuns.ts | 复用最新有效尝试选择，不把旧失败计入当前进行中任务 |
| frontend/src/features/editing/EditingWorkspace.tsx | 只修复重进、超时、dirty 离开等已复现问题 |
| frontend/src/lib/queryKeys.ts | 所有新增读取复用统一 key 工厂 |
| frontend/src/features/director/ShotDirectorSuggestionPanel.tsx | 请求中、过期、草稿应用和显式保存状态清晰 |

如需要提取轮询逻辑，可新增局部 hook，但先有两个实际复用点。不要新建全局 AgentRuntimeProvider、另一份 production store 或通用事件框架。

### 交互规则

- queued/running/cancel_requested 等按原始事实映射，终态后停止轮询。
- 页面重进能由后端快照找回任务；不依赖上一次页面内的 Promise。
- 断网只改变连接提示；不会把服务端运行状态改成 failed。
- 关闭工具面板保留草稿；切镜头/页面时让用户保存或放弃，保存失败不离开。
- 请求正在提交与生成正在进行使用不同文案。
- Candidate 预览不产生创作写请求；Formal 确认沿现有版本化 API。

### 测试与通过条件

扩展现有：

- frontend/tests/unit/SceneWorkspace.test.tsx
- frontend/tests/unit/ShotProductionActions.test.tsx
- frontend/tests/unit/EditingRecovery.test.tsx
- frontend/tests/unit/EditingWorkspace.test.tsx
- frontend/tests/unit/ProductionMonitor.test.tsx

有意义的 E2E：

1. queued → running → completed，用户不手动刷新即可看到新候选。
2. 用户在 A 写草稿，关闭面板重开仍保留；切 B 时保护草稿；B 不出现 A 的内容。
3. 保存 API 失败后草稿不丢，生成按钮仍受 dirty gate 约束。
4. 原失败 attempt 加成功 retry 后，最新状态显示成功且旧历史仍能查看。
5. 刷新或重进恢复在途成片，并最终可播放。

测试使用控制接口证明状态语义；R7 再用实际异步 Worker 验证。无需重写整套 E2E fixture 或为纯 CSS 写镜像测试。

**工期参考：0.5–1.5 日。**

## 6. R2：真实文本导演接通

### 目标

让“真实模型生成的建议”经业务入口可复现，并保持现有 proposal-only、安全和显式保存边界。先接一个公共 transport，再按 Story、Shot、Editing 逐个落地；不能一次铺开多 Agent。

### 原有与新增路径

| 文件 | 状态 | 处理 |
|---|---|---|
| backend/app/director/suggestion.py | 现有 | 保留 schema、版本及字段限制，接显式真实 transport |
| backend/app/director/recommendation.py | 现有 | 保留结构校验；真实模式不能默认落到 deterministic |
| backend/app/director/editing_suggestion.py | 现有 | 接相同文本桥接；保持 EditSession 版本二次校验 |
| backend/app/director/story_proposal.py | 现有 | 保留 draft_text→typed diff；不在解析函数中混入任意网络请求 |
| backend/app/director/assistant_context.py | 现有 | 修复经测试确认的 Shot→Scene 范围缺陷，补全冻结上下文 |
| backend/app/providers/litellm_adapter.py | 现有 | 复用 text.generate；仅为实际契约缺口修改 |
| backend/app/providers/model_profiles/resolver.py、slots.py | 现有 | 显式槽位解析及实际模型身份 |
| backend/app/director/text_transport.py | 拟新增 | 公共真实文本桥接、结构化结果、脱敏调用记录 |
| backend/app/director/story_generation.py | 拟新增 | 创意→草稿→现有提案服务；禁止直接改 Canonical |
| backend/app/api/v1/director.py、story.py | 现有 | 新能力单独 Schema/入口；保留旧手动提案入口 |
| frontend/src/routes/projects.$projectId.script.tsx | 现有 | 用户可从创意请求草稿并预览差异；手动导入保留 |

长时请求使用已有任务/Worker 基础设施。若必须持久记录异步文本请求，其最小记录先按 R4 的 DirectorTurn 字段建立；R2 仅启用“一轮生成提案”，R4 再启用自动续接。避免先造一份 TextJob、随后再造另一份重复 Turn。

迁移与模型注册是新增工作：在最新 Alembic head 之后创建唯一后继，补 model registry / metadata / RLS；不恢复旧 AgentRun 模型或旧 Budget 依赖。

### 最小垂直切片

- R2a：上下文 + 文本 bridge + Shot 提案，一次真实配置调用能得到不同于固定模板的结构化建议。
- R2b：创意生成剧本草稿，交给现有 create_story_proposal，逐项确认后形成 Scene/Shot。
- R2c：剪辑建议使用真实 Timeline 上下文，经现有 preview/apply/save 边界完成。

每个子任务独立提交和验收；R2a 完成不代表 R2b/c 自动完成。

### 关键约束

1. 使用配置的 planning.brief / planning.script / planning.storyboard；剪辑槽位映射要明文登记。
2. 文本 bridge 保存实际 model、binding、上下文指纹、输出 hash、调用状态及真实返回的用量/费用；未返回费用写 unknown，不估作实付。
3. 用现有 typed schema 检查模型输出；递归拒绝执行类字段。
4. 有界 schema repair 最多一次并记录；不得无限重试或自动换模型。
5. 缺配置/超时/错误返回失败，手动编辑可用；不能静默替换为规则建议。
6. 文本结果返回时重新校验版本和用户请求 revision；迟到结果不覆盖当前设计。
7. 不混用原始媒体 Provider 的异步恢复规则：文本通常没有可轮询远端任务 ID，结果不明应停止当前轮次，重试作为明确新尝试。
8. 不绕过既有执行审计；若已有通用文本执行缝未接通，补最小 typed 调用和记录能力，不虚构旧 Agent API。

### 验收

- 同模型对两个实质不同 Shot 上下文返回相关建议，真实调用记录与 UI 建议一一对应。
- 用户输入“不要推进镜头”，采纳后的设计及最终媒体语义请求中没有被默认风格重新加回推镜。
- 恶意字段、跨项目请求、过期版本、模型不可用、无配置均 fail closed。
- 生成建议仅写建议/轮次/调用记录；不得增加媒体生成记录或改变 Formal。
- Story 只给 brief 时可产生草稿提案；拒绝项不落地；再次请求不会重复写入同一提案。
- Editing 改节奏/字幕的建议不会触发媒体重生成。
- 单元/PG 使用受控 transport，真实模型证据合并进 R7，不为每个子任务重复支付相同测试。

**工期参考：1.5–3 日；若发现通用文本执行与持久记录有较大断层，应在 R0/R2a 即修正估算。**

## 7. R3：用户意图、Skills 与模型能力闭环

### 目标

证明“用户最终确认的创作内容”和“实际发送的请求”一致；把已有能力接实，不增设能力市场或资产时间线。

### 范围

- backend/app/director/creative_capabilities/creative_compiler.py
- backend/app/director/creative_capabilities/composer.py
- backend/app/director/creative_capabilities/shot_language_compiler.py
- backend/app/director/creative_capabilities/freeze.py
- backend/app/director/workflows/continuity.py
- backend/app/providers/eligibility.py、translation.py、runtime.py
- backend/app/production/execution_plan.py、workbench_execution.py
- backend/app/execution/product_path.py
- frontend/src/features/production/CreativeCapabilitiesPanel.tsx
- frontend/src/features/shots/api.ts

只修改证明存在断点的文件。具体 Provider Compiler 以实际 registry 解析路径为准，不创建附件中不存在的 providers/compiler.py。

### 执行步骤

1. 追踪一个项目的 template/skill/style/shot language，从 UI 选择到保存快照、编译结果、ExecutionPlan、实际 request summary。
2. 选择一个可观察的 Skill 输出和一个风格字段，证明其内容而非仅 identity 进入有效意图。
3. 对 shot_director_intent_patch 未在 creative_compiler 返回中填充的情况，检查 composer 是否另行应用；无实际接线才补。
4. 实现或验证统一优先级：显式用户值 > accepted proposal > project override > pack default。
5. 连续性从用户确认状态冻结；不得在媒体执行时临时查询“最新上一个镜头”偷偷更改 prompt。
6. UI 用现有模型候选与 execution-plan preview 展示 exact/approximate/unsupported。
7. 保留 preview→execute 的 plan_fingerprint、参考快照和 expected_shot_version。
8. 验证只配置一个有效模型、单次指定模型、Profile 变化和恢复时的身份。

### 验收案例

| 输入 | 预期 |
|---|---|
| 用户白衣、风格包默认黑衣 | 白衣保留，来源可解释 |
| 用户拒绝推镜、提案含推镜 | 拒绝部分不进入保存结果和请求 |
| 上个场景白衣、本场景明确换红衣 | 当前红衣覆盖连续性继承 |
| 选中一项镜头语言 | 必须看到语义变化；只有 provenance 不算通过 |
| 不支持尾帧但请求尾帧 | 执行前明确阻止或走已确认的适配，不悄悄丢字段 |
| 只有一个视频 Binding | 支持该请求时直接正常解析，不强制多个候选 |
| 指定 Binding 不可用 | 返回明确错误，不改用另一个 |
| 预览后 Profile 改变 | 按已有冻结/过期规则处理，不静默改变实际模型 |
| Worker 恢复 | 使用当次冻结身份，不重新路由 |

Agnes 图片 + MiniMax 视频是专项用例。没有相应有效绑定时写该组合 BLOCKED/NOT_VERIFIED；另一个模型成功不能替代。基础 V1 双创作路径使用实际已配置且满足能力的模型；若原目标明确要求 MiniMax，则专项 Gate 同样是完成条件。

**工期参考：0.5–1.5 日，以实际追踪结果为准。**

## 8. R4：有限导演推进与恢复

### 目标

让 AUTO 在一个有界创作周期中完成“分析→建议→确认→生产→结果回读→下一建议”，ASSIST 仅建议，MANUAL 仅响应请求。仅新增导演协调事实，不建立第二个生产引擎。

### 数据与文件

| 路径 | 状态 | 内容 |
|---|---|---|
| backend/app/director/turn_models.py | 拟新增，R2 异步记录可先落地 | DirectorTurn、唯一键、revision 与关联字段 |
| backend/app/director/turn_service.py | 拟新增 | 创建、claim、完成、stale、取消及恢复 |
| backend/app/director/next_action.py | 拟新增 | 有限动作白名单及确认策略 |
| backend/app/director/autonomy_policy.py | 现有 | AUTO/ASSIST/MANUAL 的实际行为差异 |
| backend/app/director/proposal_service.py | 现有 | 复用提案应用，不自动绕过版本与确认 |
| backend/app/workers/jobs.py、default.py | 现有 | 注册导演任务与恢复入口，不承担新的媒体状态机 |
| backend/app/events/outbox.py | 现有 | 复用可靠派发机制，必要时新增明确 topic |
| backend/app/api/v1/director.py | 现有 | 新增轮次创建/读取/停止/继续的 typed API |
| backend/app/shared/model_registry.py | 现有 | 注册新 ORM |
| backend/alembic/versions/ | 新迁移 | 单一后继、RLS、索引及模型一致性 |
| frontend/src/features/director/ | 现有目录 | 展示当前理解、等待原因、提案和下一确认点 |

DirectorTurn 必须关联 Project/Workspace/Actor；文本任务不伪装成真实 Shot 媒体产物。不使用一个泛化任意工具执行器替代 next_action 白名单。

### 分步实现

**R4a — 单轮持久与恢复**

- 唯一 request_key；数据库 claim；上下文与模型快照。
- 轮次状态、输出结果、提案关联在刷新和进程重启后保留。
- 无有效上下文变化时不重复生成被拒绝建议。
- 超时或结果不明停在明确错误状态，不无限循环。

**R4b — 等待与下一步**

- 在提案确认、设计保存、Formal 确认、生产终态、EditSession 保存等明确业务点通知协调器。
- 事件按 event/request key 幂等消费；消费时读取最新事实，而非信任旧事件内容。
- 对 awaiting_execution 的轮次增加低频恢复扫描，防止进程中断遗漏续接。
- 每轮最多执行一个下一步决策；每个有限目标设置步骤上限和截止时间。
- 无授权时停在 awaiting_user，已有授权覆盖则继续，不重复问同一问题。

**R4c — 用户介入**

- 用户保存新设计或撤回要求后，旧轮次变 stale。
- 切 MANUAL 后禁止新自动生产；已经提交的任务按真实远端状态处理。
- 用户拒绝建议即结束该建议分支，不换措辞反复提出同一动作。
- 所有媒体下发经 Workbench 业务服务和稳定命令 key；关键确认沿原 Gate。

### 并发和事务要求

- 下发意图与 Outbox 同事务；外部消费允许重复投递，但业务结果不可重复创建。
- 唯一键冲突返回既有轮次；状态更新带 revision。
- “命令已执行但回执未写回”时，用 idempotency key 查询既有 NodeRun/结果并重新关联。
- 同一事件多 Worker 同时消费，只有一个成功推进；另一方读取已推进状态退出。
- 暂停与取消区分：停止新的导演动作不等于远端媒体任务已取消。
- 恢复先恢复读取与关联，不发新媒体请求。
- 对决定敏感的版本包括 Shot、EditSession、用户请求、授权及已选模型；不只检查一个 UI flag。

### 必需测试

1. 同 request_key 及重复事件只产生一轮有效建议/一次命令。
2. 分别在文本调用前后、提案持久化前后、媒体下发回执前后注入中断，恢复后不重复媒体 POST。
3. 用户在文本调用期间编辑，结果 stale 且正式设计不变。
4. AUTO 到下一个确认点停止；ASSIST 不自动下发媒体；MANUAL 不主动生成建议。
5. 部分采纳后，只执行接受项；拒绝记录刷新后仍有效。
6. 后端 API 直接调用无法绕过版本、确认、授权与项目范围检查。
7. 关闭浏览器后生产完成，重新打开能看到下一步状态；下一步不依赖前端 setTimeout。
8. 达到动作/时限上限，返回可读停止原因而非无限循环。

**工期参考：1–2.5 日。持久去重和崩溃窗口比 UI Context 更重要，不为赶工省略。**

## 9. R5：生产恢复与重试验收

### 目标

先验证已有实现，再按失败类别修补。禁止把当前 Worker 改成 catch Exception 后自动重发三次。

### 主要路径

- backend/app/runtime/scheduler.py
- backend/app/workers/jobs.py
- backend/app/execution/product_path.py
- backend/app/execution/runtime_invariants.py
- backend/app/production/workbench_execution.py
- backend/app/providers/runtime.py、execution_identity.py
- backend/tests/integration/test_phase5_restart_recovery_pg.py
- backend/tests/unit/test_runtime.py、test_worker_entry.py
- backend/tests/unit/test_final_film_timeline.py

### 故障矩阵

| 故障 | 观察与判定 |
|---|---|
| 入队前 Redis 不可用 | 明确 QUEUE_UNAVAILABLE/真实状态，不返回虚假的“持续排队” |
| 远端提交成功，有任务 ID，Worker 重启 | poll 原 ID，paid create 次数不增加 |
| 提交后连接断开，没有任务 ID | unknown_submission；不自动 POST |
| 429 | 按已分类语义与 Retry-After 恢复，身份不变 |
| 任务依赖未就绪 | 下游不能使用空输入或旧的错误版本 |
| 旧 attempt 失败，新 attempt 成功 | 主界面聚合最新有效记录，历史仍可追溯 |
| 同 key、同请求重复提交 | 返回同一有效请求或已有结果 |
| 同 key、不同请求 | 冲突拒绝 |
| 下载失败 / 无效媒体 | 产物不伪装 available，错误可查 |
| 取消后远端完成 | 按 completed_after_cancel 等真实语义记录，不自动 Formal |
| 改字幕或 Timeline 后重渲染 | 图片/视频 ProviderOperation 计数为零增量 |

使用 mock upstream 可稳定证明故障语义；R7 至少完成一次真实远端任务的持久状态核对。测试环境与当前业务环境隔离，不能通过清空共享队列或用户数据库来获得通过。

**通过条件：有状态、远端请求次数、执行身份、Artifact hash/lineage 四种证据。单独“测试通过数量”不够。**

**工期参考：0.5–1 日；若复现新的执行缺陷，另列真实修复时间。**

## 10. R6：Final Film 与最终 SRT

### 目标

证明现有异步渲染反映冻结 Timeline，并补齐 MP4 对应的独立 SRT。已有 MP4 生产链复用；只修改错误与缺失的最终交付点。

### 文件范围

- backend/app/production/final_film.py
- backend/app/production/timeline_renderer.py
- backend/app/api/v1/final_film.py
- backend/app/delivery/models.py（仅当既有 ExportItem 关系不够表达时修改）
- frontend/src/features/editing/EditingWorkspace.tsx、api.ts
- backend/tests/unit/test_final_film_timeline.py、test_final_film_api.py
- frontend/tests/unit/EditingWorkspace.test.tsx、EditingRecovery.test.tsx
- 拟新增：backend/app/production/timeline_subtitles.py，集中计算最终 cue，只有确实需要独立复用才拆文件。

### 具体实施

1. 从冻结 Timeline 生成统一片段时间映射，MP4 渲染与 SRT 共用该映射。
2. 用 source in/out、timeline duration、转场重叠计算实际起点；禁止拼接原 Shot 的两秒字幕文件。
3. 字幕文本以 Timeline 为准；保持字幕禁用、空文本、多行和用户修改。
4. 独立 SRT 按现有 Artifact/ExportItem 关系存储，与 MP4 同 Timeline 版本、同导出记录。
5. API 返回可下载字幕产物信息；前端在成片历史显示“下载字幕”，无内容时明确提示。
6. 保留原同 key / request fingerprint / attempt 语义。
7. 处理中用户改 Timeline，不影响旧任务冻结输入；新保存版本后创建新的导出请求。
8. MP4 或 SRT 任一交付失败时，报告具体状态，不把不完整包显示为全成功；不要用空文件占位。

### 真渲染案例

构造三个已有视频片段 A/B/C，以 **C→A→B** 重排，给 A 裁切、B 改字幕，选择一条音轨并设置一次受支持转场，再保存 Timeline。

验收：

- HTTP 只入队；API 进程不执行 FFmpeg。
- Worker 生成可解码 H.264/AAC MP4，时长符合冻结片段与转场计算。
- 视频顺序确实是 C→A→B；裁切和字幕不是原始全文直拼。
- SRT cue 在最终时长范围内且次序正确；对齐渲染片段起点。
- 用户修改字幕后仅重做本地交付，不增加图片/视频生成调用。
- history GET 不触发重渲染。
- 首次失败后 retry 的 attempt 增加；成功结果重复请求不重复导出。
- 至少一个用例以实际 FFmpeg 执行，不能使用 app_env=test 的 _test_render 宣称真渲染。

支持的转场/字幕样式以本次实际实现为限，不为验收添加新的剪辑效果库。

**工期参考：0.5–1.5 日。**

## 11. R7：双创作路径与真实用户验收

### 验收前条件

R1–R6 对应实现及必要测试通过；候选应用能在正式 8080 入口运行；模型身份、数据库、存储和 Worker 已对齐。

当前 Goal 原文已包含必要真实 Provider 验证的授权规则。执行者先核对该授权仍有效且覆盖本次任务，覆盖则直接按最小调用次数执行，不因为需要使用现有凭据反复询问；未覆盖的新费用或外部行为才作单独处理。本次编制文档不触发调用。

### 两条主路径

**A：Template + AUTO**

1. 从内置模板创建项目，确认模板/Skill/风格快照。
2. 输入一个具体创意，让配置的真实文本模型产出剧本/镜头提案。
3. 用户修改至少一项建议并拒绝至少一项；保存后确认镜头数由内容产生。
4. AUTO 按有效授权进入关键帧生成；在 Formal 确认点停止。
5. 用户选择正式关键帧，生成视频，选择正式视频。
6. 生产完成后导演读取真实结果，提出下一条建议；不能自行替用户确认 Formal。
7. 审片创建时间注释；执行一种既有 Repair，检查旧正式结果保留直到新确认。
8. 编辑并保存 Timeline，执行 R6 的实际渲染与 MP4/SRT 下载。

**B：Free + ASSIST**

1. 自由创建，手动输入或导入剧本。
2. ASSIST 提供一条真实模型建议，用户自由修改并显式保存。
3. 手动完成关键帧、视频、Formal；无自动媒体提交。
4. 保留一个失败/恢复用例，重进页面后结果可追溯。
5. 打开/保存/重载 EditSession，采纳一条真实剪辑建议；完成成片交付。

另做 MANUAL 快速回归：不运行导演也可使用已有手动链，切换参与度不创建新 Project/Runtime。

### 数量与费用控制

- 采用最小能验证顺序、引用和交付的多个镜头；优先复用已生成正式产物测试编辑和恢复。
- 双路径分别保留完整业务身份，不用同一项目只改标签来伪造两个入口。
- 图像/视频真实调用合并验证模型能力与作品流程。
- 文本真实调用覆盖 Story、Shot、Editing，各自记录实际调用；不依靠 UI 文案证明模型运行。
- 不以 Fake Provider 代替必须真实调用的 Golden。Fake/mock 可证明错误分支，报告中单列。
- 不把 Provider 没返回的费用记成零实付；本地 FFmpeg 与远端付费调用分开。

### 跨供应商专项

若存在 Agnes 图片和 MiniMax 视频有效 Binding，执行“Agnes 正式关键帧→MiniMax 视频→Final Film”，保留两个真实模型身份与引用链。

如果没有可用 MiniMax 配置：

- 基础两条创作路径仍可继续验证；
- 该专项明确未验证；
- 若发布要求包含此组合，相关 Gate 保持 BLOCKED；
- 不将其他视频模型结果写作 MiniMax 成功。

### 证据产出

建议新增最终候选报告和 manifest，字段至少包括：

| 字段 | 要求 |
|---|---|
| candidate_sha / source_dirty | 完整 SHA，运行源码干净 |
| image_digests / OCI revision | API、Worker、dispatcher、前端明确对应 |
| migration_head | 与当前模型及镜像一致 |
| path | template_auto / free_assist / manual_regression |
| project/shot/edit_session IDs | 脱敏但可追溯 |
| text operations | 输入上下文 hash、模型/Binding、输出与提案关联 |
| media operations | 实际 Provider、远端任务 ID 摘要、尝试、结果 |
| user decisions | 采纳/拒绝/修改与版本变化 |
| artifacts | content hash、类型、正式引用与血缘 |
| timeline/export | 冻结版本、顺序、裁切、字幕、音频、MP4/SRT hash |
| assertions | PASS / FAIL / BLOCKED / NOT_VERIFIED 逐项列出 |
| evidence files | 稳定可读取位置；不只引用本地 tmp 路径 |

截图以可验证的操作断言、DOM、网络、状态和文件 hash 为主，沿仓库图像证据边界处理。不得上传凭据、短期签名 URL 或含密钥的完整请求。

**工期参考：0.5–1 日，加上真实 Provider 等待与缺陷回修。**

## 12. R8：最终候选与发布准备

### 基本原则

当前 15a0b413 的 CI/Security success 不能覆盖未来新增代码；Release skipped 不是 release PASS。旧 94b5c2d、720bde4 等 Golden 保留历史身份，不改名成新版本证据。

### 执行步骤

1. 收集 R1–R7 的修复并形成最终候选 C，冻结源码与依赖。
2. 从 C 构建精确应用镜像；记录基础镜像和应用 digest，不使用含糊 latest。
3. 对 C 执行必要质量门禁、PG/迁移、proxy/mock、前端 API/构建/E2E。
4. 从同一 C 的应用镜像运行最终真实 Golden，确认 source_dirty=false。
5. 验证 CI、Security、Release Candidate 同候选通过；普通 dev push 跳过 Release 时按当前 workflow 支持的正式入口触发。
6. 上传 C 的脱敏 Golden JSON、MP4、SRT、manifest 及校验结果，确保链接可读取。
7. 按事实更新 Goal 状态、G7/G8 合同、Release 报告与发行说明。
8. 在既有授权和分支流程下推进 review/merge/部署；不自批、不绕过保护，不把发布准备完成写成已经部署。

### 解决“提交证据后 SHA 又变了”

不要把 Golden JSON 中的 SHA 改成证据提交 SHA，也不要声称证据生成前运行了未来提交。

推荐流程：**先固定候选 C，证据以 Actions Artifact / 外部持久附件绑定 C，候选源码不再变化。** 报告使用独立证据记录或后续文档提交记录 C。

若当前 release.yml 只上传仓库内旧 evidence 目录，应补一个明确接受当前 Golden 产物并核验其 candidate_sha 的步骤；上传目录名含 github.sha 不足以证明内部文件确属该 SHA。

如果团队规定证据也必须进入发布树，则重新冻结新候选、重建并按最终规则验收；不以“只是文档”自动宣称所有同 HEAD 条件满足。仅文档提交可建立清晰源树等价关系作为补充说明，但不能替代任务合同要求的精确候选 Gate。

### 应更新的文件

- docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md
- docs/plans/professional-program-v2/task-contracts/V1-G7E-FINAL-FILM-ASYNC-TIMELINE-20260903.md
- docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md
- docs/reviews/V1-RELEASE-GATE-REPORT.md
- README.md
- 拟新增：V1-RELEASE-NOTES.md
- scripts/prove_v1_current_head_golden.py
- .github/workflows/release.yml（仅在证据校验/上传存在实证缺口时修改）

PR #12 已合并，旧 G8 里的“更新 PR #12 body 并等待合并”应调整为当前实际候选 PR / 报告，不再次把已合并的 PR 当作待办。

### 完成状态

- GOAL_BLOCKED：凭据/外部条件/证据或 Gate 仍阻塞，写具体原因。
- GOAL_READY_FOR_OWNER_MERGE：满足现行合同且仅剩其规定的最终 review/merge。
- GOAL_DONE：所有强制功能与证据条件满足，且现行合同要求的最后动作完成。
- DEPLOYED：只有确实部署并核对运行身份后才可使用，不与 GOAL_DONE 混用。

**工期参考：0.5–1 日，加 CI 与构建等待。**

## 13. 测试执行策略

### 13.1 按风险分层

| 层级 | 场景 | 使用时点 |
|---|---|---|
| 单元 | 状态映射、请求 schema、时间映射、意图优先级 | 各任务 |
| PostgreSQL | 唯一键、并发 claim、事务、RLS、版本冲突 | R2/R4/R5/R6 |
| mock upstream | 超时、429、重复投递、unknown_submission、非法输出 | R2/R4/R5 |
| 前端组件 | dirty、迟到建议、轮询终态、历史恢复 | R1/R2/R4/R6 |
| E2E fixtures | 双入口、显式 Save、Formal、版本与零写断言 | R1–R7 |
| 真实运行 | Worker 恢复、真实模型、FFmpeg、MP4/SRT | R7/最终候选 |
| Release | 源码/镜像/迁移/Gate/证据绑定 | R8 |

不为每个小修跑整套付费 Golden。非行为 Markdown/CSS 修改不新增镜像实现的测试。全量质量检查按合同 Gate 执行，额外测试仅用于解决剩余具体风险。

### 13.2 已核实的前端命令

在仓库规定的隔离环境、frontend 工作目录执行：

~~~bash
npm ci
npm run format:check
npm run lint
npm run typecheck
npm run test
npm run api:check
npm run build
npm run test:e2e
~~~

typecheck 已显式调用 @typescript/native；不要改为依赖 PATH 上的裸 tsc，不使用 --legacy-peer-deps 或 --force 绕过升级后的依赖问题。API 修改时先 npm run api:generate，再检查生成结果。

后端优先使用现有 scripts/run_quality_in_docker.ps1 与当前 CI 容器命令；实际选项以脚本为准。本方案不虚构脚本参数，不让开发者手动降低 Python/Node 来跳过已合并工具链。

### 13.3 发布硬判定

下列任何一项不满足都不能宣称完整 V1：

- 未证明真实文本模型通过产品入口生成建议。
- 用户拒绝/修改未反映到实际请求。
- API/Worker/前端镜像身份不一致。
- queued 状态只能手动刷新才完成展示。
- 同一事件/请求导致重复付费提交。
- Candidate 未确认即成为正式输入。
- 编辑只改字幕却重新生成图片/视频。
- Final Film 只证明 test renderer，没有实际 FFmpeg 文件。
- SRT 不反映最终 Timeline，或下载不可用。
- 双创作路径只跑一个，却报完整。
- Release 被跳过或 Golden 绑定旧候选。
- 无法证明跨项目隔离和已有版本守卫仍有效。

## 14. 工期、9 月 15 日目标与范围控制

用户此前提出 9 月 15 日首版目标。本方案保留它作为产品交付目标，但不把日期当成自动通过 Gate 的理由。既有 Goal 仍按 READY 任务和验证结果推进，不要求用户逐次说“继续”。

上面的工期为**新增有效开发工作量估算**，不能相加后当作承诺日期；R0、R5、R6 很可能以复用验证为主，真实导演桥接与持久轮次则是主要不确定项。

### 目标节奏

| 时间窗口（UTC+8） | 应达到的结果 | 不满足时的处理 |
|---|---|---|
| 9/7–9/8 | R0、R1，跑通现有媒体与成片读取；明确所有真实缺陷 | 先修阻塞，停止非必要美化 |
| 9/8–9/10 | R2，真实文本导演最小垂直链；R3 意图/能力闭环 | 若只是规则建议，明确导演链未完成 |
| 9/10–9/12 | R4 有限推进；R5 恢复；R6 MP4/SRT | 不扩展自治范围、模板数量或剪辑效果 |
| 9/13–9/14 | R7 双路径，修复实测问题并冻结候选 | 不在 Golden 后插入新功能 |
| 9/15 | R8 的最终候选及实际发布边界处理 | 若 Gate 未满足，提供准确候选状态与缺口，不改写 DONE |

这是**压缩目标窗口，不是已证明可完成的承诺**。R0 应给出基于剩余任务的更新估算；若新增文本运行能力和恢复机制大于预算，完整目标可能跨过 9/15。

### 允许延后

- SSE 持久事件桥接与全局事件框架。
- 更多模板、风格包及额外供应商。
- 复杂资产状态时间线。
- 多步自主审片与自动择优、无限自动重做。
- 复杂 UI 微动效、全量 CSS 重构、额外导出格式。
- 无测量证据支撑的性能指标优化。

### 不能静默删减

真实导演接通、用户意图一致、显式确认、运行恢复、成片与 SRT、同候选证据是本次修订定义的完整范围。若为演示只交付“手动制作 + 导演建议”，应明确称受限候选，不称完整 AUTO 目标已完成。产品范围实质变更才需要用户决策；日常修复和继续任务不重复询问。

## 15. Task Contract 模板与执行规则

每次实施一个有边界的任务，合同至少记录：

~~~text
Task: R?-子任务名称
Parent: 既有 G?/UI/Model Supply 合同
Baseline: 完整 dev SHA
Problem: 实际复现行为与影响
Current evidence: 已读取的代码、测试、运行事实
Scope: 现有文件 / 拟新增文件
Behavior: 用户能看到的前后差异
Invariants: 版本、确认、身份、幂等、项目隔离
Acceptance: 可执行断言
Tests: 最小相关检查 + 所属 Gate
Evidence: source/image/migration/provider/artifact
Result: PASS / FAIL / BLOCKED / NOT_VERIFIED
Next: 下一个满足依赖的任务
~~~

执行规则：

1. 不根据文件名或旧 COMPLETE 推断当前完整能力。
2. 已存在且本候选证明满足的工作，登记 ALREADY_PROVEN，给出证据，不重复实现。
3. 新增设计不得写作“当前已实现”；未实测不得写实测 PASS。
4. 修改与测试先在当前任务范围内闭环，再进入下一任务。
5. 一般类型错误、测试失败、迁移修复不作为停机理由；在任务内修好。
6. 遇到确实影响产品范围或缺少必要外部条件，给具体阻塞与可继续的工作。
7. 只编制文档不启动开发 Goal；用户另行要求按方案实施时，按照本流程执行。
8. 不将整个项目再次定义成一个重构大任务；以能交付真实作品为最终判断标准。

## 16. 设计—任务—验收追踪

| 设计章节 | 实施任务 | 核心验收 |
|---|---|---|
| 2–3 基线与修正 | R0 | 不把旧问题当新缺口，不把历史证据当当前 PASS |
| 6 真实导演 | R2 | 真模型、真上下文、typed proposal、显式保存 |
| 6.4 / 8 意图与能力 | R3 | 用户选择与实际请求一致 |
| 6.5–6.6 有限推进 | R4 | 持久去重、用户介入、确认点、浏览器关闭可恢复 |
| 7 Production Runtime | R5 | 无重复 POST、正确重试、冻结身份 |
| 9 Canvas 工作流 | R1 | 自动刷新、草稿不丢、阶段动作、预览零写 |
| 10 成片交付 | R6 | 真 FFmpeg、冻结 Timeline、MP4/SRT |
| 13 双路径验收 | R7 | Template+AUTO / Free+ASSIST 及 MANUAL 回归 |
| 12–14 候选与权威 | R8 | 同 SHA/image/migration/evidence，更新真实状态 |

## 17. 证据入口

- [核查基线 15a0b413](https://github.com/zwb2002-yjy/dramaforge-p0/commit/15a0b41338d51eeb2da162180869f45291fd5aef)
- [#65 实际整合内容与测试记录](https://github.com/zwb2002-yjy/dramaforge-p0/pull/65)
- [Goal 状态与合同索引](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md)
- [G7E 验收要求](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/docs/plans/professional-program-v2/task-contracts/V1-G7E-FINAL-FILM-ASYNC-TIMELINE-20260903.md)
- [G8 验收要求](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md)
- [Release workflow](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/.github/workflows/release.yml)
- [Final Film 单测：契约与测试替身边界](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/tests/unit/test_final_film_timeline.py)
- [Runtime 单测：未知提交等边界](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/backend/tests/unit/test_runtime.py)
- [现有前端命令与依赖](https://github.com/zwb2002-yjy/dramaforge-p0/blob/15a0b41338d51eeb2da162180869f45291fd5aef/frontend/package.json)

更完整的逐文件源码链接见配套设计方案第 15 节。所有现状判断均固定在核查基线；实施前按 R0 检查 dev 增量。
