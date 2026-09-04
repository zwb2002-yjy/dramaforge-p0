# DramaForge 编码 Agent — V1 统一创作主链执行入口

**状态：USER-AUTHORIZED / GOAL-DRIVEN / 强制执行**

本文件是 DramaForge 当前编码 Agent 的最高层执行导航。它不替代产品设计、七方案原文或 Task Contract；它把当前 Owner 已确认的产品方向、架构边界、连续执行方式和完成条件内化为 Agent 的默认行为。

Agent 的任务不是完成一次局部修改后等待，而是：

> 从当前 `dev` 的真实状态出发，连续完成 DramaForge V1 统一创作主链 Goal，直到形成经过完整 Gate、真实 Provider Golden 和 Final Film 验证的 Release Candidate。

---

## 1. 权威依据与冲突优先级

每次启动或恢复执行，按以下顺序读取：

1. `docs/plans/professional-program-v2/README.md` 中最新 Owner amendments；
2. Owner 提供的《DramaForge V1 最终创作与导演架构设计方案》；
3. Owner 提供的《DramaForge V1 统一创作主链 Goal 执行方案》；
4. Professional 七方案中与当前 Task 类型对应的原文，按 README 规定的冲突优先级；
5. 当前 bounded Task Contract；
6. `AGENT_EXECUTION_PROTOCOL.md`；
7. 当前代码、迁移、测试、CI、运行时和 commit-bound 证据。

在 G0 尚未把两份 Owner 文档写入仓库前，以当前执行会话提供的文件为准；G0 完成后必须通过 README 的 Owner amendments 入口定位，不得复制出多份互相冲突的版本。

冲突处理：

- 当前 Owner amendment 覆盖七方案中已经撤回的 Legacy compatibility / rollback 要求；
- 七份原始方案正文与 `source-integrity.json` 保持不变；
- 产品事实以最终创作与导演设计方案为准；
- Review 技术冲突与实施顺序仍按七方案 README 的既定优先级；
- Task Contract 只能缩小本次改动范围，不能改写 Owner Goal；
- 当前代码和测试说明“现在是什么”，不能反过来否定 Owner 已确认的目标；
- 旧 P0、旧总纲、`docs/current/`、旧 checkpoint 和历史 Release Board 仅作历史证据，不能决定新范围、架构或完成状态。

禁止为本 Goal 再创建一份竞争性的 Master Plan。新增工作只能写成边界清晰的 Task Contract。

---

## 2. 当前 Goal

唯一作品主链：

```text
Project
→ Template Start / Free Start
→ Story / Script Proposal
→ Canonical ScriptDocument / Episode / Scene / Shot
→ Asset / Style / Skills / Director Planning
→ Shot Design
→ Keyframe / Image Candidate → Formal
→ Video Candidate → Formal
→ Review → Experiment / Repair
→ EditSession / Timeline
→ Director Editing Recommendation
→ Manual / Assisted Editing
→ Save / Export
→ Final Film
```

必须支持的两个独立维度：

```text
CreativeStartType
├─ TEMPLATE
└─ FREE

DirectorAutonomy
├─ AUTO
├─ ASSIST
└─ MANUAL
```

它们始终进入相同的：

```text
Project
Workbench / Canvas
Scene / Shot
Candidate / Formal
Production Runtime
ProviderOperation / Artifact
EditingAdapter / EditSession
Final Film lineage
```

绝不能创建：

```text
QuickPipeline
ProfessionalPipeline
TemplatePipeline
AutoPipeline
ManualPipeline
```

---

## 3. 启动基线

本 Goal 编制时已核实：

- 远端 `dev` HEAD 为 `8ac35463097bc0a769f969df1a457a51802ccda1`；
- `dev → main` PR #12 为 Open；
- 当前 HEAD 的 CI 与 Security workflow 成功；
- `P10-LEGACY-HARD-REMOVAL-20260902` 已完成；
- Quick、旧 Creation 媒体链、旧 controlled Director、固定十镜、旧 Batch/Budget 执行依赖及双 Runtime 分支已经硬清理；
- `P10-STORY-AUTHORING-PROPOSAL-CHAIN-20260902` 是清理完成后的第一个 `READY / NOT STARTED` Task；
- 当前 Shot 与 Editing suggestion 仍以用户先输入 `user_instruction` 为主；
- 当前项目创建只包含名称和画幅，创建后直接进入 Production；
- 当前不存在产品级 CreativeTemplate 与 DirectorAutonomy；
- 旧真实 Golden 绑定 `66eb4d28...`，不能作为最终 Goal HEAD 的发布证据。

以上 SHA 只用于说明 Goal 起点。Agent 每次启动必须重新检查真实 HEAD、git status、Task 记录、CI 和 Gate；若代码已前进，应基于新证据继续，不得退回或重复已经完整证明的工作。

---

## 4. 必须保护并复用的现有能力

以下能力已经存在，不得为了实现新产品语义而重建第二套：

- Project / ScriptDocument / Episode / Scene / Shot；
- Scene Workbench、Canvas、CandidateTray、ShotStrip、右侧操作面板；
- Asset / AssetVersion / AssetVersionReference / ShotReferenceBinding；
- Genre Profile、Style Pack、Shot Language Pack、Creative Skill 与 CreativeCapabilityCompiler；
- DirectorSuggestion 的 structured validation、proposal-only、dirty 与 stale 边界；
- DirectorProposal / DirectorProposalItem / typed command / partial apply；
- Candidate / Formal / Experiment / Repair；
- ExecutionPlan / ProductionGraph / NodeRun / ProviderOperation / Artifact；
- ProductionModelProfile / ModelManifest / ExecutionModelResolution / Provider Binding identity freeze；
- 统一 media runtime、Outbox、Arq Worker、幂等、局部重跑和 Artifact lineage；
- EditSession / EditingAdapter / Timeline / Save / Reopen / Export；
- Editing proposal 与 Production facts 的只读边界；
- Docker quality Gate、PostgreSQL migration/contract、OpenAPI/generated client、Playwright 与 release evidence 体系。

Agent 先复用这些 seam，再补产品缺口；不得因为名称不完全一致就另起 ORM、API、Runtime 或页面体系。

---

## 5. Canonical 架构事实

### 5.1 作品事实唯一

正式作品事实只有：

```text
Project / ProjectCreativeProfile
ScriptDocument / Episode / Scene / Shot
Asset / AssetVersion / References
Candidate / Formal
Review / Experiment / Repair
EditSession / Timeline / Final Film
```

Story draft、Template default、Director recommendation、Creative Skill 输出和模型响应都不是第二套正式事实。它们必须通过：

```text
Analysis
→ Typed Proposal
→ Exact Diff Preview
→ User Whole / Partial Accept / Reject
→ Apply to Draft or Canonical Command
→ Explicit Save
→ Versioned Canonical Facts
```

Director 不得偷偷写正式事实。用户未采用的建议视为当前决定，不反复追问；只有新证据产生新的实际风险时才能再次建议。

优先级固定为：

```text
用户显式值
> 已采用 Proposal
> Project override
> Template / Genre / Style / Skill / Shot-Language default
```

### 5.2 执行事实唯一

```text
Canvas / Canonical Scene-Shot Facts
→ ExecutionPlan
→ ProductionGraph
→ NodeRun
→ ProviderOperation
→ Artifact
```

- ProductionGraph 是执行图，不是用户创作画布；
- Route 不直接写 SQL；
- Service 不绕过统一调度、Outbox 或 Worker；
- Artifact 二进制只进入对象存储；
- 所有媒体执行必须冻结 model、binding、connection/credential revision、manifest、mode 与 reference identity；
- 用户选择模型 X 时不得静默执行 Y；
- unsupported 或 missing input 必须 fail closed，Provider request count = 0；
- 不允许自动模型 fallback；
- Agent 不新建第二套 Generation、AIJob、media service 或 Runtime 真相。

### 5.3 Editing 与 Production 分层

Editing 允许修改：

- Clip order、trim、duration；
- Subtitle、audio、music、transition；
- Timeline metadata 与基础编辑效果。

Editing 禁止修改：

- `Shot.formal_*_artifact_id`；
- `Asset.current_version_id`；
- ProductionGraph / NodeRun / ProviderOperation；
- Formal production lineage。

Timeline 能解决的问题生成 Editing Proposal；不能解决的问题只能显式生成 Production Repair Proposal，不能从剪辑界面偷偷重生成。

---

## 6. CreativeTemplate 的特殊边界

产品级 CreativeTemplate 回答：

> 这类作品通常如何组织，以及项目初始化时应预置哪些创作结构。

当前代码中的：

```text
backend/app/director/workflows/template_nodes.py
backend/app/director/workflows/library.py
backend/app/production/templates.py
WorkflowTemplateSpec
```

属于 Production Graph 执行模板。不得把它们改造成产品创建模板。

V1 产品 Template 应使用与现有 Genre / Style / Skills 相同的代码版本化 Registry，并把实例化 Snapshot 保存到 ProjectCreativeProfile。至少包含：

```text
key / version / contract_hash
name / category / description
required_asset_slots / optional_asset_slots
recommended_genre
recommended_style_ids
recommended_skill_ids
recommended_shot_language
shot_planning_strategy
generation_strategy
review_strategy
editing_strategy
```

Template 只能：

```text
CreativeTemplateSpec
→ Instantiate
→ ProjectCreativeProfile
→ Asset Slot Requirements
→ Creative defaults
→ Story Proposal Context
```

Template 不得：

- 固定 Shot 数；
- 直接创建 ProductionGraph、NodeRun 或 ProviderOperation；
- 直接调用 Provider；
- 在项目实例化后继续暗中控制用户已经修改的事实；
- 因模板版本升级静默修改历史项目 Snapshot。

V1 只实现三个真实模板：

1. 双人对白反转；
2. 单人情绪独白；
3. 自由短剧基础模板。

不建设模板市场、模板后台或通用模板编辑器。

---

## 7. DirectorAutonomy 的特殊边界

`DirectorAutonomy` 是新的独立语义：

```text
AUTO
ASSIST
MANUAL
```

禁止复用已删除的 `ExperienceMode`、Quick/Workbench 或任何旧 Project mode。

它只影响：

- 是否主动分析；
- 是否主动显示推荐；
- 建议频率；
- 默认 UI 信息密度；
- 自动推进程度；
- 确认频率。

它不能影响：

- Project/Scene/Shot 身份；
- ExecutionPlan / ProductionGraph；
- Model resolution；
- Provider / Runtime；
- Artifact / EditingAdapter。

行为底线：

| 行为 | AUTO | ASSIST | MANUAL |
|---|---|---|---|
| 主动分析 | 是 | 是 | 否 |
| 主动生成 Proposal | 是 | 是 | 仅用户请求 |
| 自动写 Canonical Facts | 否 | 否 | 否 |
| 自动确认 Candidate → Formal | 否 | 否 | 否 |
| 默认高级参数 | 收起 | 可展开 | 展开 |
| 用户随时接管 | 是 | 是 | 已接管 |

AUTO 的 Candidate → Formal、锁定事实覆盖、Formal 删除和 Final Export 确认是 DramaForge 产品内 Gate，不是编码 Agent 的停机条件。测试或 Golden 可以在已授权场景中显式完成这些产品操作，无需等待 Owner 逐步发消息。

---

## 8. Proactive Director Recommendation

Director 必须从“用户先写一句要求”升级为基于服务端事实主动分析。

结构至少包含：

```text
DirectorRecommendation
├─ scope
├─ category
├─ current_state
├─ suggested_change
├─ reason
├─ expected_effect
├─ risk
├─ affected_facts
├─ base_versions
└─ typed_operations
```

类别 schema 至少支持：

```text
STORY
PERFORMANCE
BLOCKING
SHOT_SIZE
CAMERA_ANGLE
CAMERA_MOTION
COMPOSITION
PACING
REFERENCE
CONTINUITY
MODEL_STRATEGY
QUALITY
REPAIR
EDITING
```

V1 主动检测至少真实覆盖：

```text
PERFORMANCE
CAMERA_ANGLE / CAMERA_MOTION
SHOT_SIZE
PACING
REFERENCE
CONTINUITY
```

Director Context 必须从服务端读取：

- Story、Scene、Shot；
- Character/Asset references；
- Style、Skills、Shot Language 与 CompiledCreativeIntent；
- 前后镜头；
- Candidate / Formal；
- Quality evidence 与 Repair history。

客户端不得上传并伪装这些 Canonical facts。

实现要求：

- 复用 DirectorProposal / DirectorProposalItem / typed command；
- 不新建第二套 recommendation database；
- 支持 whole / partial / reject；
- stale、dirty、locked fact 与用户手改优先；
- recommendation patch 递归禁止 Provider、Runtime、SQL、Worker、NodeRun、Artifact 字段；
- 推荐本身不创建媒体；
- 表演建议必须把抽象情绪转为视线、呼吸、停顿、微表情、手部动作、Blocking 和台词节拍，而不是只追加形容词 Prompt；
- 真实文本模型必须经过既有 `text.generate` / LiteLLM 模型与凭据边界；
- Director service 不得私开 HTTP、硬编码模型或绕开 ProviderOperation 证据；
- 测试可注入 deterministic transport；生产无模型时应明确 unavailable/needs_human，不能把占位规则冒充真实模型推理。

Editing recommendation 继续复用现有 EditSession 和 typed proposal，至少支持：

```text
ORDER
TRIM
PACE
TRANSITION
SUBTITLE
AUDIO
MUSIC
REACTION_HOLD
ENDING_BEAT
```

---

## 9. 永久禁止恢复的旧语义

不得重新引入：

- Quick Project / Professional Project；
- Quick Pipeline / Professional Pipeline；
- Quick → Professional 转换；
- `/quick` 产品路由或 mock surface；
- `ExperienceMode`；
- 固定十镜或任何固定镜头数产品规则；
- Legacy materialization / historical Quick execution；
- 旧 Creation media path；
- 旧 controlled Director workflow；
- Budget / ProductionBatch 作为媒体执行前置 Gate；
- Provider runtime feature flag 双路由；
- Character 子表、名称猜测、Prompt 猜测或双读身份兼容路径；
- 自动模型 fallback；
- Template / Skill / Style 直接调用 Provider；
- Director 绕过 Proposal 修改 Canonical facts；
- Editing 反写 Production facts。

`scripts/check_canonical_surface.py` 必须持续扩展并作为 Gate，阻止旧语义回流。

---

## 10. Goal 工作顺序

按依赖顺序连续执行：

```text
G0  权威基线与架构登记
G1  Story Authoring Proposal Chain
G2  CreativeTemplate 与 ProjectCreativeProfile
G3  DirectorAutonomy 行为策略
G4  Proactive Director Recommendation
G5  Creation UX 与统一 Canvas
G6  OpenCut Director 主动剪辑建议
G7  统一主链 E2E 与 Golden Project
G8  Current-HEAD Release Gate 与交付
```

选择规则：

1. 恢复所有未闭合 Task 的真实状态；
2. 先处理当前依赖链中最高优先级的 `READY` Task；
3. 每次只实现一个 bounded Task Contract；
4. Task 完成后自动重算 Goal Gate 并继续；
5. 如果某工作包已经被代码和测试完整满足，记录 `SKIPPED_AS_ALREADY_PROVEN` 及证据；
6. 不以旧文档标题或 Agent 自述作为已完成证据；
7. 不提前并行有依赖关系的后续 Task；
8. 默认串行；只有任务真正独立、路径不重叠且执行协议允许时才隔离并行。

各工作包的详细 Outcome、Gate 和范围以《DramaForge V1 统一创作主链 Goal 执行方案》为准。

当前起点应先执行 G0；G0 通过后，直接执行现有 Story Task Contract，而不是再重新设计旧 Creation 链。

---

## 11. 连续执行控制循环

每次 Agent 启动、恢复或完成 Task 后，都执行：

```text
读取 Owner Goal 与当前 Task Contract
→ control open / tail
→ git status / worktree / branch / remote
→ 核对当前 HEAD、migration head、CI 和已有证据
→ 计算最高优先级 READY Task
→ 写/补 bounded Task Contract
→ 记录 STARTED
→ 实现最小范围
→ Focused Tests
→ Required Full Gate
→ 独立复核 diff 与架构边界
→ 更新合同与证据
→ Commit + Push dev（按执行协议）
→ 记录 COMPLETED
→ 重算 Goal Gate
→ 自动进入下一 READY Task
```

以下都不是停机理由：

- 完成一个 Task；
- 完成一次 commit 或 push；
- 完成一个工作包；
- 普通编译、lint、type、unit、E2E 失败；
- migration、OpenAPI、generated client 或契约漂移；
- 可在当前权限内修复的 CI、容器、端口或依赖问题；
- 需要调用已经授权的付费 Provider。

Agent 应诊断、修复、回归并继续。

允许暂停并报告 `GOAL_BLOCKED` 的情况仅限：

1. 缺少会改变 Canonical 产品结果的 Owner 决策；
2. 必需凭据不存在且无法通过现有项目配置获得；
3. 外部服务、权限或受保护分支阻止所有后续 Ready Task；
4. Owner amendments 与七方案出现不能按既定优先级消解的冲突；
5. 只剩 Owner 才能完成的批准、`dev → main` 合并或发布动作。

一个外部阻塞 Task 不阻止其他无依赖的 `READY` Task。

---

## 12. 付费 Provider 授权

Owner 已授权本 Goal 使用项目现有配置与凭据执行必要的付费 Provider 调用，包括：

- Story/Director 所需的真实文本模型验证；
- 图片与视频能力验证；
- Template + AUTO / Free + ASSIST 的真实主链；
- 最终 current-HEAD Golden 与 Final Film。

Agent 不得因为会产生费用而暂停、再次询问或把真实验证降级成 mock。

同时必须：

- 合并验证场景；
- 优先复用有效 Artifact；
- 将付费调用控制在完成 Goal 与证明 Gate 所需的最小次数；
- 不在普通 unit/E2E 循环反复调用真实 Provider；
- 每次真实调用保留 ProviderOperation、模型/绑定身份、状态、Artifact 和 lineage；
- 对 submit-unknown、超时和可能已计费请求不得盲目重试；
- 不记录 secret、完整凭据或未脱敏 Provider 响应；
- 不伪造成本、调用、质量或 Golden 成功。

此授权只覆盖本 Goal，不代表建设预算、账单、计费 UI 或对账系统；这些仍在 V1 范围外。

---

## 13. Task Contract 纪律

每个 Task 开始前必须在：

```text
docs/plans/professional-program-v2/task-contracts/
```

建立或确认合同，至少包含：

- Task ID；
- Goal 工作包；
- Current Evidence / Drift；
- 用户可观察 Outcome；
- owned paths；
- explicit out-of-scope；
- migration/API/UI 影响；
- success criteria；
- focused tests；
- required regression；
- paid Provider 计划（若有）；
- exact completion evidence。

合同必须足够小，使一个提交可以被独立 review。不得借一个 Task：

- 顺手重写 Worker/Runtime；
- 扩张到团队权限、计费、模板市场、完整三维或自动经验学习；
- 恢复 Legacy 兼容；
- 删除与本 Task 无关的用户改动；
- 用无关重构掩盖产品变更。

Task 完成必须有代码、测试或运行证据。自然语言“已实现”不算完成。

---

## 14. Git、账本与合并

严格遵守 `AGENT_EXECUTION_PROTOCOL.md`：

- `.agent-control/PROGRESS.jsonl` 只追加，不入 Git；
- 使用 STARTED / COMPLETED / FAILED / PAUSED / MERGED 的准确语义；
- Agent 不记录 MERGED；
- 日常串行 Task 在根 worktree 的 `dev` 完成、提交并推送；
- 只有并行隔离或 hotfix 使用 `agent/<task-id>` 与独立 worktree；
- `main` 只通过受保护的 `dev → main` PR 更新；
- Agent 不批准或合并自己的 PR；
- 只有 `@zwb2002-yjy` 可以批准并合并；
- 禁止 force push、历史重写、`git reset --hard`、`git clean -fd` 或覆盖用户改动；
- dirty worktree 不生成正式 release evidence。

如果本文件与执行协议在“当前产品目标/任务选择”上冲突，以本文件和 Owner Goal 为准；如果在“账本、分支、worktree、Git 安全”上冲突，以 `AGENT_EXECUTION_PROTOCOL.md` 为准。

---

## 15. 每个 Task 的验证要求

按风险选择 focused tests，但跨域 Task 必须覆盖受影响层。

### Backend / Data

- Ruff / Mypy；
- unit；
- PostgreSQL migration、RLS、FK、unique、version、idempotency；
- stale fail-before-mutation；
- no Provider call / no NodeRun 的负向 Gate；
- Alembic 单 head、无 drift。

### API / Security

- Owner、workspace、project cross-boundary 拒绝；
- CSRF；
- unknown field fail closed；
- proposal patch 递归禁止 execution/provider/SQL/artifact 字段；
- OpenAPI export 与 generated client 一致。

### Frontend

- lint / format / typecheck；
- unit；
- build；
- Playwright；
- stale、dirty、whole/partial/reject；
- Template/Free 与 AUTO/ASSIST/MANUAL 共用路由和 Workbench。

### Architecture Regression

- canonical surface scan；
- repository guardrails；
- no Quick / ExperienceMode / fixed-shot；
- no Template/Autonomy runtime switch；
- no Director direct canonical mutation；
- no Editing production mutation；
- no second media path；
- no automatic model fallback。

### Release Candidate

- 干净 exact-commit worktree；
- Docker quality Gate；
- PostgreSQL upgrade；
- full backend / PG / frontend / Playwright / security；
- commit-bound real Provider Golden；
- 15–30 秒、真人写实、角色对白、多 Shot Final Film；
- source SHA、image SHA、evidence source 一致；
- gateway、API、Scene、Editing 与 Final artifact health/availability。

旧 `66eb4d28...` Golden 只作历史证据，不能证明最终候选。

---

## 16. V1 范围冻结

本 Goal 必须交付：

- Story proposal-first 创作链；
- Template Start / Free Start；
- 三个 V1 CreativeTemplate；
- AUTO / ASSIST / MANUAL；
- 主动 Shot recommendation；
- whole / partial / reject；
- 创建页与统一 Canvas 分层体验；
- 主动 Editing recommendation；
- Editing → Repair 显式分流；
- Template + AUTO 与 Free + ASSIST 两条 E2E；
- current-HEAD real Provider Golden；
- Final Film Export 与 lineage；
- Release Candidate Gate。

明确不做：

- 多人协作、组织权限、复杂审批；
- 预算、账单、计费 UI、对账；
- 历史 Quick 恢复；
- 自动经验学习、经验归因、历史方案推荐；
- 跨项目智能复用；
- 模板市场或模板管理后台；
- 通用节点画布；
- 完整三维场景系统；
- 片段级视频修复；
- 人脸 embedding 或伪造自动一致性评分；
- 自动模型 fallback；
- 为 Template/Autonomy 新建 Runtime。

新增范围必须先取得 Owner 明确确认，再创建独立 bounded Task Contract。

---

## 17. Goal 完成标准

只有以下全部成立，才能报告 Goal 完成：

1. Legacy hard removal 持续通过；
2. Idea 可通过 proposal/diff/partial apply 写入 Canonical Script/Scene/Shot；
3. Template Start 与 Free Start 创建同一种 Project；
4. CreativeTemplate 只参与初始化，不拥有 Runtime；
5. AUTO/ASSIST/MANUAL 可切换且不改变执行身份；
6. Director 能基于服务端事实主动推荐表演、动作、机位、景别、节奏和 Reference；
7. 用户可以 whole/partial/reject；
8. 用户手改、locked、dirty 与 stale 始终优先；
9. Candidate/Formal、Experiment、Repair 边界保持；
10. 所有媒体进入统一 NodeRun/ProviderOperation/Artifact；
11. OpenCut 是正式主链尾段；
12. Editing recommendation 可部分采用；
13. 剪辑不能解决的问题显式成为 Repair Proposal；
14. Template + AUTO 与 Free + ASSIST 共用 Runtime 和 EditingAdapter；
15. 新项目 legacy execution call = 0；
16. 不存在固定镜头数产品规则；
17. 最终候选完整质量、安全、迁移与 E2E Gate 通过；
18. 最终候选完成 commit-bound real Provider Golden；
19. 至少一部真实作品 Export 成 Final Film；
20. Release evidence、镜像与 source SHA 一致；
21. `dev → main` PR 具备 Owner 可独立审查的完整证据。

若 1–20 已完成，只剩 Owner 批准/合并，报告：

```text
GOAL_READY_FOR_OWNER_MERGE
```

Owner 已批准并合并且发布证据仍与 merge candidate 一致后，才报告：

```text
GOAL_DONE
```

不得因为单个 Task、单次测试、旧 Golden 或“功能基本可用”提前完成。

---

## 18. 最终回报格式

```text
STATE: GOAL_DONE | GOAL_READY_FOR_OWNER_MERGE | GOAL_BLOCKED

FINAL_HEAD:
MIGRATION_HEAD:
PR:

DELIVERED:
- Story
- CreativeTemplate / Free Start
- DirectorAutonomy
- Proactive Director Recommendation
- Creation / Canvas UX
- OpenCut Director Integration
- Golden / Final Film

ARCHITECTURE_PROOF:
- one Project/Scene/Shot
- one Runtime
- one Artifact lineage
- one EditingAdapter
- legacy execution call = 0

VERIFICATION:
- backend
- PostgreSQL
- frontend
- Playwright
- security
- real Provider Golden
- deployment/health

EVIDENCE_PATHS:

REMAINING_OWNER_ACTION:
```

最终回报必须引用准确 commit、测试结果、真实 ProviderOperation 与证据路径；不能只罗列 Agent 做过的动作。
