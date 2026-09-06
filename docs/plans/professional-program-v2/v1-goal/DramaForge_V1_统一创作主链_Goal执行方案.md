# DramaForge V1 统一创作主链 Goal 执行方案

## 0. 文档定位

**执行目标：** 在当前 `dev` 基础上，把 DramaForge 收敛成可发布的 V1 Director-first AI 影视生产工作台。

**执行方式：** Goal 驱动，不制定日期，不按阶段等待人工继续指令。Agent 每完成一个有边界的 Task，就执行验证、提交、重算 Gate，并自动继续下一个最高优先级的 `READY` Task，直到满足本方案的 `GOAL_DONE` 条件。

**设计依据：**

1. 《DramaForge V1 最终创作与导演架构设计方案》；
2. `docs/plans/professional-program-v2/` 中的 Professional 七方案；
3. 2026-09-02 Owner 对 Legacy compatibility hard removal 的修订；
4. 当前 `dev` 的代码、迁移、测试、Gate 和真实运行证据。

本方案是当前 V1 创作与导演收敛的 **Owner Goal 执行覆盖层**，不修改七份原始方案正文，也不另建与七方案竞争的第二套 Master Plan。应把本方案与设计方案登记到 `professional-program-v2/README.md` 的 Owner amendments 中，并为每个实施单元建立一个边界清晰的 Task Contract。

---

# 1. 当前工程基线

## 1.1 已核实状态

截至本方案编制时：

- 仓库：`zwb2002-yjy/dramaforge-p0`；
- 分支：`dev`；
- 当前远端 HEAD：`8ac35463097bc0a769f969df1a457a51802ccda1`；
- 最新提交：`ci: install git inside policy containers`；
- `dev → main` PR：#12，仍为 Open；
- 当前 HEAD 的 GitHub CI 与 Security workflow 均为 `success`；
- `P10-LEGACY-HARD-REMOVAL-20260902` 已标记 `COMPLETE`；
- Quick 产品面、旧 Creation 媒体链、旧 controlled Director、固定十镜、旧 Batch/Budget 执行依赖及双 Runtime 分支已经完成硬清理；
- Canonical surface scan 已阻止这些旧语义重新进入产品代码。

最近一轮 Legacy 清理完成证据包含：

- Backend Ruff / Mypy 通过；
- Backend unit：848 passed；
- PostgreSQL migration 升级至 `20260902_0051`，无 drift；
- PostgreSQL integration：17 passed；
- Frontend unit：97 passed；
- Playwright：13 passed；
- OpenAPI、API contract、frontend lint/typecheck/build 通过；
- LiteLLM integration、依赖审计、repository guardrails 通过。

## 1.2 已有能力，后续必须复用

以下不是待重建项：

- Project / ScriptDocument / Episode / Scene / Shot；
- Scene Workbench：Canvas、CandidateTray、ShotStrip、右侧操作面板；
- Asset / AssetVersion / AssetVersionReference / ShotReferenceBinding；
- Creative Capability Registry；
- Genre Profile、Style Pack、Shot Language Pack、Skill Composer；
- Director Shot Suggestion 的 proposal-only、stale、dirty 与 draft/save 边界；
- DirectorProposal / DirectorProposalItem / typed command / partial apply 基础；
- Candidate / Formal / Experiment / Repair；
- ExecutionPlan / ProductionGraph / NodeRun / ProviderOperation / Artifact；
- Provider model resolution、binding identity freeze 与统一 media runtime；
- EditSession / EditingAdapter / Timeline / Director Editing Suggestion / Save / Reopen / Export；
- Production facts 与 Editing facts 的只读边界。

## 1.3 当前真实缺口

| 缺口 | 当前证据 | Goal 要求 |
|---|---|---|
| Story 创作主链尚未开始 | `P10-STORY-AUTHORING-PROPOSAL-CHAIN-20260902` 为 `READY / NOT STARTED` | Idea 到 Canonical Script/Scene/Shot 的 proposal-first 闭环 |
| 没有产品级 CreativeTemplate | 当前 `WorkflowTemplateSpec` 是执行图模板 | 新建只负责项目初始化的 CreativeTemplate，绝不拥有 Runtime |
| 没有 DirectorAutonomy | `ExperienceMode` 已被清理；当前无 AUTO/ASSIST/MANUAL 项目事实 | 新增可随时切换的 Director 行为策略 |
| Director 仍以用户先输入为主 | Shot 与 Editing suggestion 都要求 `user_instruction` | 增加基于服务端事实的主动分析与结构化推荐 |
| 镜头建议不能完整部分采用 | 当前 Shot 面板主要是整组应用到本地草稿 | 复用 typed proposal，实现按事实组部分采用或拒绝 |
| 创建入口尚未产品化 | 当前只填项目名和画幅，创建后进入 Production | 提供 Template Start / Free Start 与 Autonomy 选择，并进入创作主链 |
| 当前 HEAD 没有新的真实 Golden | 已有 Golden 绑定旧候选 `66eb4d28...` | 最终候选必须重新完成当前 commit-bound Golden 与发布门禁 |

---

# 2. 最终 Goal

实现并证明以下唯一作品主链：

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

同时证明：

```text
Template + AUTO
Free + ASSIST
Free + MANUAL
```

使用的是同一个：

```text
Project
Scene / Shot
Candidate / Formal
Production Runtime
ProviderOperation / Artifact
EditingAdapter / EditSession
Final Film lineage
```

---

# 3. 不可破坏的架构原则

## 3.1 两个正交维度

```text
CreativeStartType
├─ TEMPLATE
└─ FREE

DirectorAutonomy
├─ AUTO
├─ ASSIST
└─ MANUAL
```

- `CreativeStartType` 只决定项目初始化时预置多少创作结构；
- `DirectorAutonomy` 只决定 Director 的主动程度、默认 UI 密度、建议频率和确认频率；
- 两者都不得成为 Runtime、Provider、ProductionGraph 或 Editing 的执行身份。

## 3.2 Product Template 与 Workflow Template 必须分开

当前代码中的：

```text
backend/app/director/workflows/template_nodes.py
backend/app/director/workflows/library.py
WorkflowTemplateSpec
```

属于 **Production Graph 执行模板**，不能被改造成用户创建项目时选择的 CreativeTemplate。

新增的 CreativeTemplate 只允许：

```text
Template Spec
→ Instantiate
→ ProjectCreativeProfile
→ Asset Slot Requirements
→ Genre / Style / Skill / Shot-Language Defaults
→ Story Proposal Context
```

禁止：

```text
CreativeTemplate
→ ProductionGraph
→ NodeRun
→ ProviderOperation
```

## 3.3 Canonical Facts 唯一

- Story proposal、Director recommendation、Template default 都不是第二套作品事实；
- 只有用户预览并采用后写入的 ScriptDocument / Episode / Scene / Shot / ProjectCreativeProfile 才是正式事实；
- 显式用户值优先于已采用建议，已采用建议优先于项目默认，项目默认优先于 Pack/Template 默认；
- Director 不得绕过 Proposal、Preview、Partial Apply、Save、Version、Stale Guard；
- 未采用建议视为用户当前决定，不得反复追问；只有出现新的事实风险时才能再次提示。

## 3.4 旧语义永久禁止恢复

不得重新引入：

- Quick Project / Professional Project；
- Quick Pipeline / Professional Pipeline；
- Quick → Professional 转换；
- `ExperienceMode`；
- 固定十镜；
- Legacy materialization / historical Quick execution；
- 旧 controlled Director workflow；
- Budget / ProductionBatch 作为媒体执行前置 Gate；
- 第二个 Provider 或 media runtime；
- 自动模型 fallback；
- Template、Skill 或 Style 直接调用 Provider。

---

# 4. Agent Goal 运行协议

## 4.1 启动动作

Agent 开始执行 Goal 时必须先：

1. 读取 `agent.md`、`AGENT_EXECUTION_PROTOCOL.md`；
2. 读取 Professional 七方案索引及本 Goal 对应 Owner amendment；
3. 读取当前 `dev` HEAD、git status、最近任务记录与当前 Task Contract；
4. 核对 `P10 Legacy Hard Removal` 的完成证据仍然有效；
5. 运行或读取当前基线 Gate，不能根据文档状态猜测代码状态；
6. 将当前 HEAD、dirty 状态、migration head、测试状态写入 Goal 执行记录。

## 4.2 连续执行循环

```text
读取当前真实状态
→ 计算最高优先级 READY Task
→ 建立一个有边界的 Task Contract
→ 实现最小必要改动
→ Focused Tests
→ Full Required Gate
→ Review Diff / Canonical Boundary
→ Commit
→ 更新执行记录
→ 重算 Goal Gate
→ 自动进入下一个 READY Task
```

完成单个 Task 不是停机条件。Agent 不需要等待用户发送“继续”。

## 4.3 允许停机的条件

仅以下情况允许返回 `GOAL_BLOCKED`：

1. 需要新的 Owner 产品决策，且不同选择会改变 Canonical 数据或主链；
2. 必需凭据不存在、权限不足、外部服务不可用或受保护分支阻止继续；
3. 发现当前设计与七方案存在不能通过既定优先级消解的冲突；
4. 需要 Owner 才能完成的批准、`dev → main` 合并或发布动作。

一般测试失败、迁移失败、类型错误、契约漂移、CI 错误和实现缺陷不属于停机条件；Agent 应在当前 Task 内修复并继续。

本 Goal 已明确授权使用项目现有配置和凭据完成必要的付费 Provider 调用，包括文本模型的真实能力验证、图片/视频生产和最终 Golden。Agent 不得因调用会产生费用而暂停或再次请求确认；应合并验证场景、复用已生成 Artifact，并将付费调用控制在完成 Goal 与证明 Gate 所需的最小次数。每次调用都必须保留 ProviderOperation、模型身份、结果状态和 Artifact lineage，不得通过绕开统一执行链来省略证据。

## 4.4 提交与合并边界

- 日常实现遵循仓库现有 `dev` 与 Task Contract 流程；
- 每个提交必须对应一个可验证的 bounded Task；
- 不将中间失败证据伪装为完成证据；
- Agent 不批准或合并自己的 PR；
- `dev → main` PR #12 的最终批准与合并仍由 Owner 完成。

---

# 5. Goal 工作包

工作包按依赖顺序执行。若当前代码和证据已经完整满足某一工作包，Agent 可以记录 `SKIPPED_AS_ALREADY_PROVEN`，但必须给出代码、测试与 Gate 证据，不能只依据旧文档标题跳过。

## G0 — 权威基线与架构登记

### 目标

把最终设计方案和本执行方案登记为当前 Owner amendment，防止后续 Agent 继续按已废弃的 Quick / Professional 双轨理解开发。

### 必须完成

- 在 `professional-program-v2/README.md` 增加当前创作与导演架构 Owner amendment；
- 保存设计方案与本 Goal 执行方案，保持七份原文不变；
- 将 `docs/architecture/CANONICAL_PRODUCT_PATH.md` 的基线从旧 `e8da0da` 更新到执行时真实 HEAD；
- 明确 CreativeTemplate 与 `WorkflowTemplateSpec` 的命名和职责边界；
- 为本 Goal 建立状态记录和后续 Task Contract 索引；
- 复跑 source integrity、plan reference 与 canonical surface checks。

### Gate

- 七方案原文哈希不变；
- README、Canonical Product Path、Goal 与 Task Contract 引用一致；
- 没有第二份冲突 Master Plan；
- Legacy forbidden surface 扫描继续通过。

---

## G1 — Story Authoring Proposal Chain

### 依据

直接执行现有 `P10-STORY-AUTHORING-PROPOSAL-CHAIN-20260902`，它是当前硬清理完成后的第一个 `READY` Task。

### 目标

```text
Idea
→ Creative Brief Proposal
→ Story Direction Proposal
→ Script Draft
→ Structure Diff
→ Preview / Partial Accept / Reject
→ ScriptDocument / Episode / Scene / Shot
```

### 实施要求

- 先做 proposal/diff persistence 的独立 schema 与 API review；
- Proposal 生成和预览不修改 Canonical Story；
- Apply 只能执行用户明确接受的 typed operations；
- expected version 不匹配时 fail closed；
- Apply 幂等，重复请求不能重复创建 Scene/Shot；
- Shot 数量由被接受的故事结构动态产生；
- Apply 本身不产生任何 Provider 请求或媒体任务；
- 应用后的 Scene / Shot Workbench 是后续媒体生成唯一入口；
- 不复活 Creation、Quick、controlled Director 或固定镜头数。

### UI 结果

用户能看到：

- 当前故事事实；
- Director 提出的故事方向；
- 结构新增、修改、删除的明确 Diff；
- 全部采用、部分采用、拒绝；
- stale / dirty 提示；
- 保存后的 Script、Scene、Shot 结果。

### Gate

- unit + PostgreSQL 覆盖 idempotency、partial apply、stale、canonical writes；
- 明确证明 Apply 的 Provider call = 0；
- frontend contract、unit、Playwright 覆盖 preview/apply/reject；
- OpenAPI 与 generated client 同步；
- 现有 Scene Workbench、P10 canonical、migration Gate 不回归。

---

## G2 — CreativeTemplate 与 ProjectCreativeProfile

### 目标

建立产品级 Template Start / Free Start，但不建立 Template Runtime。

### 建议最小模型

```text
CreativeTemplateSpec                 # V1 代码版本化 Registry
├─ key / version / contract_hash
├─ name / category / description
├─ required_asset_slots
├─ optional_asset_slots
├─ recommended_genre
├─ recommended_style_ids
├─ recommended_skill_ids
├─ recommended_shot_language
├─ shot_planning_strategy
├─ generation_strategy
├─ review_strategy
└─ editing_strategy

ProjectCreativeProfile               # 每个 Project 一行 Canonical Profile
├─ project_id
├─ start_type: TEMPLATE | FREE
├─ created_from_template_key?
├─ template_version?
├─ template_contract_hash?
├─ director_autonomy
├─ selected_genre
├─ selected_style_ids
├─ selected_skill_ids
├─ selected_shot_language
├─ asset_slot_requirements
├─ strategy_snapshot
└─ version
```

V1 只有少量内置模板，优先采用与现有 Skills / Style Packs 一致的代码版本化 Registry，不建设模板管理后台或通用数据库模板市场。项目只保存来源身份和实例化后的 Snapshot，后续模板升级不得静默改变已有项目。

### V1 模板

1. 双人对白反转；
2. 单人情绪独白；
3. 自由短剧基础模板。

### 实例化要求

- `POST /projects` 在一个事务内创建 Project 与 ProjectCreativeProfile；
- `TEMPLATE` 必须提供有效 template key/version；
- `FREE` 不得偷偷套用完整模板；
- Template 只写初始化 Profile、资产槽需求和 Story proposal context；
- Template 不直接创建固定 Shot 列表；
- Template 不创建 ExecutionPlan、ProductionGraph、NodeRun 或 ProviderOperation；
- 用户后续修改后的 Canonical facts 永远优先于模板默认；
- 不复用已删除的 `ExperienceMode` 字段或 enum。

### 主要代码影响区

- `backend/app/director/creative_capabilities/`：CreativeTemplate contract、registry、library；
- Project ORM / service / API：ProjectCreativeProfile 与事务化实例化；
- Alembic：新表、约束、RLS、索引；
- `frontend/src/routes/index.tsx` 与项目 API；
- OpenAPI、generated types、unit/PG/E2E。

不得把产品 Template 实现在：

- `backend/app/director/workflows/template_nodes.py`；
- `backend/app/director/workflows/library.py`；
- `backend/app/production/templates.py`。

### Gate

- Template 与 Free 创建后都只产生同一种 Project；
- Template 实例化 Provider call = 0；
- Template 实例化 NodeRun / ProductionGraph count = 0；
- Template version/snapshot 可追踪；
- 修改 Template Registry 不改变历史项目 Snapshot；
- 三个模板与 Free Start 的 PG/API/E2E 均通过。

---

## G3 — DirectorAutonomy 行为策略

### 目标

新增 AUTO / ASSIST / MANUAL，但只影响 Director 行为和 UI，不影响 Runtime。

### 实施要求

- `DirectorAutonomy` 是独立 enum，不复用 Quick/Workbench；
- 存入 ProjectCreativeProfile，并带 optimistic version；
- 用户可在项目中随时切换，不迁移 Project，不复制 Scene/Shot；
- 建立集中式 `DirectorAutonomyPolicy`，禁止各 UI/API 分散写 if/else；
- Policy 只返回：是否主动分析、是否显示建议、默认 UI 密度、是否需要确认；
- Media execution service、model resolver、ProviderRuntime 不读取 `DirectorAutonomy`；
- MANUAL 下 Director 关闭也必须完成完整生产与剪辑；
- AUTO 也不能绕过 Candidate → Formal、付费生产确认、锁定事实、删除 Formal 和 Final Export Gate。

### 最小行为矩阵

| 行为 | AUTO | ASSIST | MANUAL |
|---|---|---|---|
| 主动分析当前阶段 | 是 | 是 | 否 |
| 主动显示推荐 | 是 | 是 | 否 |
| 自动生成 Proposal | 是 | 是 | 仅用户请求 |
| 自动写 Canonical Facts | 否 | 否 | 否 |
| 自动确认 Candidate → Formal | 否 | 否 | 否 |
| 自动发起付费媒体生产 | 仅已明确授权范围 | 否 | 否 |
| 隐藏高级参数 | 默认 | 可展开 | 默认展开 |
| 用户随时接管 | 是 | 是 | 已接管 |

### Gate

- 三档切换不会改变 ProductionGraph 构建结果；
- 同一 Shot、同一输入下 model resolution 不因 Autonomy 改变；
- MANUAL 完整链 E2E 继续通过；
- AUTO 关键 Gate 均需用户确认；
- stale、dirty、locked facts 优先级不被 Autonomy 绕过。

---

## G4 — Proactive Director Recommendation

### 目标

把当前“用户输入一句要求后生成建议”升级为“Director 基于当前服务端事实主动发现问题并提出结构化建议”。

### 统一结构

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

V1 主动检测必须真实覆盖：

```text
PERFORMANCE
CAMERA_ANGLE / CAMERA_MOTION
SHOT_SIZE
PACING
REFERENCE
CONTINUITY
```

### Context 规则

Director 必须从服务端读取并版本化：

- Story / Scene / Shot Canonical facts；
- Character/Asset references；
- Style、Skills、Shot Language 与编译后的 Creative Intent；
- 前一镜与后一镜；
- Candidate / Formal；
- Quality evidence 与 Repair history。

客户端不得上传并伪装这些 Canonical facts。

### 生成与执行边界

- 复用现有 CreativeCapabilityCompiler、Skills、Style、Shot Language；
- 复用 DirectorProposal / DirectorProposalItem / typed command，不新建第二套 Proposal 真相；
- 当前 Shot suggestion 的 transport seam 可以扩展，但必须保持结构化校验和 fail-closed；
- 若接入真实文本模型，必须走已批准的 `text.generate` / LiteLLM 模型解析与凭据边界，不得在 Director service 内私开 HTTP 或硬编码模型；
- 测试可使用 deterministic transport；生产若无已配置文本模型，应明确显示 unavailable/needs_human，不得把占位规则结果冒充真实模型推理；
- 不允许自动 fallback 到另一个模型；
- 推荐只生成 Proposal，不能直接生成媒体或改 Canonical facts；
- 用户可全部采用、按 operation 部分采用或拒绝；
- 用户手改、stale、dirty、locked facts 始终优先。

### 表演能力要求

Recommendation 不能只追加形容词 Prompt。必须把抽象情绪转换为可拍事实，例如：

```text
情绪
→ 视线
→ 呼吸
→ 停顿
→ 微表情
→ 手部动作
→ Blocking
→ 台词节拍
```

### Gate

- 无用户 instruction 也能基于 Server Context 生成有效推荐；
- 推荐包含 current/suggested/reason/effect/risk；
- 支持 whole/partial/reject；
- stale proposal fail closed；
- 未采用建议不修改 Shot，不触发媒体；
- 应用建议只更新明确接受的设计事实；
- Provider、Runtime、SQL、Artifact 等执行字段不能混入 recommendation patch；
- 至少一条真实上下文推荐在 Golden 中被用户采用并进入后续 Shot 生产。

---

## G5 — Creation UX 与统一 Canvas 体验

### 目标

让大众用户和专业用户从同一个项目入口进入同一个创作工作台。

### 创建页

```text
创建作品
├─ 从模板开始
│  ├─ 双人对白反转
│  └─ 单人情绪独白
└─ 自由创建

导演参与度
├─ 导演自动 AUTO
├─ 导演辅助 ASSIST
└─ 手动控制 MANUAL
```

### 创建后的导航

- 新项目进入 Story / Script 创作阶段，不再默认跳到空 Production 页；
- Template 项目展示已实例化的创作结构和待补资产槽；
- Free 项目展示最小 Story/Asset/Style/Skill 入口；
- 两者进入相同 Project 路由与 WorkstationShell；
- 不出现“升级专业模式”“转换项目”“Quick/Professional”文案。

### Canvas 分层

- 默认层：当前画面、导演建议、候选、下一步；
- 展开层：表演、镜头、运镜、节奏、Reference 的部分采用；
- 高级层：Camera、Lens、Pose、Gaze、Blocking、Action、Style、Skill、Model、Experiment、Repair；
- 只改变信息密度，不复制页面或生产链；
- Director Sidebar 可收起，Canvas 始终是作品控制中心。

### Gate

- Template/Free 创建与打开 E2E；
- AUTO/ASSIST/MANUAL 选择与切换 E2E；
- 同一项目 URL 身份不因 Autonomy 改变；
- 三档共用同一 Scene Workbench、CandidateTray、ShotStrip；
- 不出现第二个 Shot 编辑器或第二个 Project state store；
- UI 不暴露 NodeRun、ProviderOperation 等底层术语作为大众主操作。

---

## G6 — OpenCut Director 主动剪辑建议

### 目标

复用当前 EditSession、EditingAdapter、typed proposal 和 Suggestion UI，把 Director Autonomy 延伸到剪辑尾段。

### 实施要求

- 不重写 OpenCut Integration；
- Editing recommendation schema 支持：ORDER、TRIM、PACE、TRANSITION、SUBTITLE、AUDIO、MUSIC、REACTION_HOLD、ENDING_BEAT；
- AUTO/ASSIST 可基于 Timeline 主动发现节奏、反应镜头、跳切、字幕、对白与音乐问题；
- MANUAL 只在用户请求时生成建议；
- 复用 expected session version、stale、typed operation、partial apply；
- Timeline 能解决的问题只产生 Editing Proposal；
- Timeline 不能解决的问题必须显式产生 Production Repair Proposal；
- 不得从 Editing suggestion 偷偷创建 NodeRun 或重新生成 Shot；
- Editing 永远不能反向修改 `Shot.formal_*`、Asset current version、ProductionGraph 或 ProviderOperation。

### Gate

- 主动剪辑建议无需用户先写 instruction；
- whole/partial/reject 均有 UI 与 E2E；
- stale EditSession fail closed；
- Timeline apply 后 production lineage 不变；
- `Can Fix In Timeline?` 的 Yes/No 两条分支都有测试；
- No 分支只创建 Repair Proposal，不直接执行 Repair。

---

## G7 — 统一主链 E2E 与 Golden Project

### 目标

用两条用户路径证明“不同起点、不同 Director 参与度、同一生产与剪辑事实体系”。

### E2E A：Template + AUTO

```text
Template
→ Story Proposal
→ User Confirm
→ Auto Director Recommendation
→ Partial Apply
→ Shot
→ Production
→ Candidate
→ Formal
→ OpenCut Timeline
→ Director Editing Recommendation
→ User Confirm
→ Export
```

### E2E B：Free + ASSIST

```text
Free Project
→ Manual Story / Style / Skills
→ Story Proposal Partial Apply
→ Director Recommendation
→ Production
→ Experiment / Repair
→ Formal
→ OpenCut Manual Timeline
→ Editing Suggestion Partial Apply
→ Export
```

### 必须证明

- 两条路径共用 Project/Scene/Shot 表；
- 两条路径共用 ExecutionPlan/ProductionGraph/NodeRun；
- 两条路径共用 Provider model resolution；
- 两条路径共用 Artifact lineage；
- 两条路径共用 EditingAdapter/EditSession；
- Candidate 与 Formal 分离；
- Experiment 不污染 Formal；
- Repair 只重跑明确范围；
- Shot 数量不固定；
- Legacy execution call = 0；
- Final Film 可追溯到 Timeline version 与 Formal Shot 集合。

### 测试层级

1. Backend unit；
2. PostgreSQL migration / RLS / contract；
3. Frontend unit / API contract / type / build；
4. Playwright 两条完整主链；
5. Canonical surface / repository guardrails；
6. 当前候选 commit 的真实 Provider Golden；
7. 当前候选镜像与部署健康验证。

---

## G8 — Current-HEAD Release Gate 与交付

### 目标

把最终实现收口为 commit-bound、source-clean、可复现的 V1 Release Candidate。

### 必须完成

- 从最终候选的干净 worktree 运行完整 Docker quality Gate；
- PostgreSQL 从受支持起点升级到最终 migration head；
- OpenAPI 生成与 frontend client 无 drift；
- 全量 backend、PG integration、frontend、Playwright 通过；
- Security、dependency audit、repository policy 通过；
- 真实 Provider Golden 绑定最终 source commit，不能复用 `66eb4d28...` 的旧结果；
- Golden 至少产出一部 15–30 秒、真人写实、角色对白、多 Shot 的可播放 Final Film；
- 记录实际 ProviderOperation、Artifact、Formal Shot、EditSession、Timeline version 与 Final Artifact lineage；
- 付费 Provider 已获本 Goal 授权，不需要另行确认；开发中只做必要的最小能力验证，完整真实调用集中到最终 Golden，避免无证据的重复消耗；
- 构建并核验与 source SHA 一致的发布镜像；
- 更新 V1 Release Gate Report、Canonical Product Path 和 README 当前状态；
- 将 `dev → main` PR #12 更新为真实 release evidence；
- Agent 到 Owner 合并边界后返回 `GOAL_READY_FOR_OWNER_MERGE`，不得自行批准或合并。

---

# 6. 全局测试与回归要求

每个 Task 至少执行 focused tests；每个跨域 Task 和最终 Goal 必须执行完整 Gate。

## 6.1 数据与迁移

- Alembic 单 head；
- 干净 PostgreSQL upgrade；
- 现有 canonical 项目可读；
- 新表具备 workspace/project ownership、RLS、FK、unique、version 约束；
- 不迁移或恢复已废弃 Quick 历史数据；
- 不新增双读、兼容 alias 或 legacy fallback。

## 6.2 API 与安全

- CSRF、Owner、workspace/project cross-boundary 拒绝；
- expected version / stale fail-before-mutation；
- unknown field fail closed；
- Template、Recommendation、Proposal payload 递归拒绝 Provider/Runtime/SQL/Artifact 字段；
- OpenAPI 与 generated types 同步。

## 6.3 产品事实

- Template default 不覆盖用户事实；
- Director proposal 未接受时 Canonical facts 不变；
- Partial Apply 只修改选中 operations；
- Candidate 不自动晋升 Formal；
- Experiment 与 Repair 不污染未指定范围；
- Editing 不覆盖 Production facts；
- Final Film lineage 完整。

## 6.4 反双轨测试

测试必须断言：

- 没有 Quick route/API/type；
- 没有 Professional Project type；
- 没有 `ExperienceMode`；
- 没有 template/autonomy runtime switch；
- 没有固定 Shot 数；
- 没有 Template/Skill/Style 直连 Provider；
- 没有 Director 绕过 Proposal 写 Canonical facts；
- 没有 Editing 反写 Production；
- 没有第二套媒体执行 service。

---

# 7. V1 范围冻结

## 7.1 本 Goal 必须交付

- Story proposal-first 创作链；
- Template Start / Free Start；
- 三个 V1 CreativeTemplate；
- AUTO / ASSIST / MANUAL；
- 主动 Shot recommendation；
- Recommendation 全部/部分采用/拒绝；
- 创建页与 Canvas 分层体验；
- 主动 Editing recommendation；
- Timeline → Repair 显式分流；
- 两条统一主链 E2E；
- 当前 HEAD 真实 Provider Golden；
- Final Film Export 与 lineage；
- V1 Release Candidate Gate。

## 7.2 本 Goal 明确不做

- 多人协作、组织权限、复杂审批；
- 预算、账单、计费 UI、对账系统；
- 历史 Quick 项目恢复；
- 自动经验学习、经验归因、历史方案推荐；
- 跨项目智能复用；
- 模板市场或模板后台；
- 通用节点画布；
- 完整三维场景系统；
- 片段级视频修复；
- 人脸 embedding 或伪造自动一致性评分；
- 自动模型 fallback；
- 为 Template、AUTO、MANUAL 另建 Runtime。

任何新增范围都必须先由 Owner 明确确认，再写入新的 bounded Task Contract；不得在实现当前 Goal 时顺手扩张。

---

# 8. GOAL_DONE 判定

只有以下全部满足，Agent 才能返回 `GOAL_DONE` 或 `GOAL_READY_FOR_OWNER_MERGE`：

1. Legacy hard removal 继续通过，旧语义未回流；
2. Idea 可通过 proposal/diff/partial apply 落到 Canonical Script/Scene/Shot；
3. Template Start 与 Free Start 均可创建同一种 Project；
4. CreativeTemplate 只参与初始化，不拥有 Runtime；
5. AUTO/ASSIST/MANUAL 可切换且不改变执行身份；
6. Director 能基于服务端事实主动推荐表演、动作、机位、景别、节奏和 Reference；
7. 用户能全部采用、部分采用或拒绝；
8. 用户手改、锁定事实、dirty 与 stale 始终优先；
9. Candidate/Formal、Experiment、Repair 边界保持；
10. 所有媒体进入统一 NodeRun/ProviderOperation/Artifact；
11. OpenCut 是正式主链尾段；
12. Editing recommendation 可部分采用；
13. 剪辑不能解决的问题显式转成 Repair Proposal；
14. Template + AUTO 与 Free + ASSIST 两条 E2E 共用 Runtime 和 EditingAdapter；
15. 新项目 legacy execution call = 0；
16. 不存在固定十镜或其他固定镜头数产品规则；
17. 最终候选的完整质量、安全、迁移与 E2E Gate 通过；
18. 最终候选完成 commit-bound 真实 Provider Golden；
19. 至少一部真实作品 Export 成 Final Film；
20. Release evidence、镜像与 source SHA 一致；
21. `dev → main` PR 已具备 Owner 可独立审查的完整证据。

若 1–20 已完成而只剩 Owner 批准/合并，返回：

```text
GOAL_READY_FOR_OWNER_MERGE
```

不得因为“代码基本完成”“测试大部分通过”或“旧 Golden 曾经通过”提前声明 Goal 完成。

---

# 9. Agent 最终回报格式

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
- legacy call = 0

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

这份回报必须引用最终 commit、测试结果和证据文件，不能只描述 Agent 做过什么。
