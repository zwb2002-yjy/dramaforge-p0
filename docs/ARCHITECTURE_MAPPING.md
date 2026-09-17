# ARCHITECTURE_MAPPING — 当前代码 → 目标架构映射

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Date: 2026-09-15 / Base: dev 5ea45d6 / Alembic head: 20260910_0066

本文件是 Phase 1 产物：**当前代码到目标架构的映射，以及真实差距清单**。

- 目标世界观见 [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md)；
- 依赖规则见 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md)；
- 术语见 [DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md)。

**取证方式：** 用 `scripts/arch_import_scan.py`（本次新增，只读）对
`backend/app/**.py`（278 个文件）做 AST import 静态扫描，输出层间依赖矩阵与逐边明细。
本文件所有结论均可由该脚本复现，不依赖人工目测。

**本轮未修改任何业务代码、DB 迁移或 API。**

---

## 一、层间依赖矩阵（扫描实测）

`src → dst` 表示存在多少条"来源模块 → 目标模块"的跨层 import 边。
**标记 FORBIDDEN 的行与 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) §三 冲突。**

```text
  contract -> production   1 FORBIDDEN
  creative -> domain       1
  creative -> shared       2
  director -> contract    21
  director -> domain      47
  director -> other        9
  director -> production  18
  director -> provider    24 FORBIDDEN
  director -> shared      53
    domain -> creative     1 FORBIDDEN
    domain -> other        1
    domain -> production   3
    domain -> shared      24
  frontend -> contract     5
  frontend -> creative     7
  frontend -> director    40
  frontend -> domain      54
  frontend -> other       10
  frontend -> production  37
  frontend -> provider    30
  frontend -> shared      38
     other -> frontend     2
     other -> provider     1
     other -> shared       2
production -> contract     5
production -> director     4
production -> domain      41
production -> other        7
production -> provider    34
production -> shared      43
  provider -> domain       8
  provider -> other       16
  provider -> production   6 FORBIDDEN
  provider -> shared      21
    shared -> director     3
    shared -> domain       5
    shared -> other        2
    shared -> production   3
    shared -> provider     2
```

复现命令：`py -3.12 scripts/arch_import_scan.py --matrix`

**结论摘要：**

- **Creative 出向完全干净**（只有 1 条 `→ domain`、2 条 `→ shared`，且无出向违规）。
- 真正需要处理的耦合：`director → provider`（24）、`production → director`（4）、
  `provider → production`（6）、`contract → production`（1）、
  `domain → creative`（1），以及 `shared → 全部`（13）。
- `director → domain`（47）与 `production → provider`（34）是**规则允许**的方向。

---

## 二、八个必查问题的结论

### 问题 1：是否存在 Creative 代码反向依赖 Director Runtime？

**结论：不存在。这是全场最干净的一块。**

`director/creative_capabilities/`（15 文件 / 2107 行）的全部 `app.*` import 只有三类：

| 目标 | 边数 | 判定 |
|---|---|---|
| `app.director.creative_capabilities.*`（自引用） | 14 | 包内 |
| `app.shared.errors` | 2 | 允许（shared 被所有层依赖） |
| `app.assets.models` | 1 | 允许（`director → domain` / `creative → domain`） |

对 `app.director.runtime` / `app.director.workflows` / `app.director.<业务模块>` /
`app.production` / `app.providers` / `app.execution` / `app.workers` / `app.api`
的 import **实测为 0**。

**含义：** Creative Layer 的逻辑解耦（Phase 2）**不需要拆代码**，只需要
① 锁定依赖 Gate 防止回归；② 决定物理目录是否迁移。原方案担心的"Creative 反向依赖
Director Runtime"在当前代码中并不存在。

**但要反向记录一条：唯一的 `domain → creative` 边构成违规。**

| # | 边 | 判定 | 真实性质 |
|---|---|---|---|
| V-6 | `access/projects.py → director.creative_capabilities.creative_templates` | **违规（规则层面）** | 项目创建时要校验 `template_key` 并记录 `created_from_template_key`，因此 domain 需要知道模板目录。这是**语义合理的调用，但方向违规**：模板目录属 Creative Layer。处置二选一：① 把模板查找改为由 application/API 层注入（推荐，保持 domain 纯净）；② 在 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) 正式声明 `domain → creative` 为**允许例外**（因为 Creative Profile 本身就挂在 Project 上） |

> 本项是本次盘点**修正了初稿判断**的发现：初稿按"执行方案未提及"记为允许，
> 但按已落地的依赖规则它就是违规。规则与语义在此冲突，必须由 Owner 决定，
> 不得默认放过（见 §五 待决问题 7）。

---

### 问题 2：是否存在 Production 代码直接调用 Director 业务？

**结论：存在，4 条越界边，其中 2 条是真实架构违规。**

| # | 边 | 判定 | 真实性质 |
|---|---|---|---|
| V-1 | `contracts/production_commands.py → production/reference_intents.ShotReferenceIntent` | **违规** | 契约层反向依赖实现层。`ShotReferenceIntent` 是被 `ProductionCommand.references` 引用的公共类型，应定义在 contract 层，由 production 反向 import |
| V-2 | `production/repair_service.py → director.workflows.contracts.ShotParticipationPlan` | **违规** | 修复执行直接消费 Director workflow 的数据类型 |
| V-3 | `production/golden_project.py → director.proposal_models` + `director.assistant_models` | **违规** | Golden project fixture 构造 Director 提案用于演示；属测试/种子数据，不该让 Production 生产代码依赖 Director 业务模型 |
| V-4 | `workbench/shot_service.py → director/turn_service.DirectorTurnService` | **违规** | Shot workbench 服务直接驱动 Director 轮次 |

**反向也存在一条越界：**

| # | 边 | 判定 | 真实性质 |
|---|---|---|---|
| V-5 | `director/workflows/library.py → production/templates` | **越界但方向合理** | Director 的模板目录消费 Production 的图定义构造器。因为该构造器就是 ProductionGraph 的 `definition` 生产者，故**物理归属应在 production，逻辑调用允许**；建议改为 `production → creative.contracts` 风格的类型契约，而非直接 import 实现 |

**Scheduler 侧参考（非违规）：** `api/v1/workbench.py::create_execution` 已经正确地
走 `ProductionCommands.submit_user_execution()`，是本次盘点中**唯一完全合规的
生产入口**，可作为 Phase 5 的目标形态样板。

---

### 问题 3：是否存在 Provider 代码包含创作决策？

**结论：不存在真实违规。但有一条需要收敛的 Director → Provider 硬耦合。**

`app/providers/**`（65 文件 / 12944 行）对 `app.director.*` import **实测为 0**。

创意相关字样只出现在三处，均非违规：

| 位置 | 内容 | 判定 |
|---|---|---|
| `providers/fake.py:41,96,159,247` | 假 Provider 的 fixture 视觉风格/VisualBible 文本 | KEEP——它是测试替身，不是创作决策 |
| `providers/intents.py:1` | "Unified creative-intent domain models for image/video generation" | KEEP——这正是 `EffectiveProviderRequest` 的位置 |
| `providers/manifest.py:5` | "creative intent → model ability layer" 三层切分注释 | KEEP——与宪法第四节一致 |

**真正的问题在反方向：** Director 有 24 条指向 Provider 的边，且
`director/text_transport.py::DirectorTextRuntimeAdapter` 直接
import `providers.registry` / `providers.model_profiles.{resolver,slots}` /
`providers.contracts.{common,text}`，并在 `generate_structured` 内读取
`registered.adapter.provider_id`——即 **Director 直接持有 Provider adapter**。

判定：Director 需要文本 LLM 才能工作，属
[MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) §四.3 的**受限例外**，但当前形态是
"直接 import adapter registry"，不是"经由 `app/contracts/` 声明的端口"。这是
Phase 2/5 需要收敛的点：把文本推理能力抽成 contract 端口，Director 只依赖端口。

**未发现** Director 直接调用**媒体** Provider 的证据，符合宪法禁令。

---

### 问题 4：是否存在 Node 被滥用成普通函数包装？

**结论：不存在滥用。10 个 node_type 全部通过准入规则。**

持久化 `node_type` 枚举（`execution/models.py`）只有十个值，逐一按
[PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md) §五 判定：

| node_type | 独立失败 | 独立重试 | 显著成本 | 独立产物 | 异步等待 | 血缘追踪 | 下游依赖 | 判定 |
|---|---|---|---|---|---|---|---|---|
| `prompt_compose` | ✓ | ✓ | — | ✓(document) | — | ✓ | ✓ | **BORDERLINE → KEEP** |
| `keyframe` | ✓ | ✓ | ✓ | ✓(image) | ✓ | ✓ | ✓ | KEEP |
| `identity_review` | ✓ | ✓ | — | ✓(document) | — | ✓ | ✓ | KEEP |
| `video` | ✓ | ✓ | ✓ | ✓(video) | ✓ | ✓ | ✓ | KEEP |
| `video_review` | ✓ | ✓ | — | ✓(document) | — | ✓ | ✓ | KEEP |
| `voice` | ✓ | ✓ | — | ✓(audio) | — | ✓ | ✓ | KEEP |
| `subtitle` | ✓ | ✓ | — | ✓(subtitle) | — | ✓ | ✓ | KEEP |
| `composite` | ✓ | ✓ | — | ✓(video) | — | ✓ | ✓ | KEEP |
| `continuity_review` | ✓ | ✓ | — | ✓(document) | — | ✓ | ✓ | KEEP |
| `export` | ✓ | ✓ | — | ✓(export_package) | — | ✓ | ✓ | KEEP |

- **无 DEMOTE_TO_FUNCTION、无 DELETE。**
- `prompt` 作为独立 `node_type` **不存在**（只出现在纯节点判定集合中），说明历史上
  已经做过一次正确的降级。
- 唯一边界项是 `prompt_compose`：无 Provider 成本、无异步等待，但**有独立产物**
  且被 `keyframe` 显式依赖，并已被标记为纯上游节点
  （`production/workbench_execution.py::_PURE_UPSTREAM_NODE_TYPES`）。保留。

**含义：** Phase 4 的 "Node 清理" 在当前代码中**基本无事可做**。原方案假设的
"只有字符串拼接作用的 Node / 只有 enum 转换作用的 Node" 已不存在。

---

### 问题 5：是否存在多个 Graph 概念？

**结论：领域 Graph 概念只有一个。存在的是"模板目录分散"，不是"两套 Graph 世界观"。**

**不是违规的证据（关键）：**

`director/workflows/contracts.py` 明确定义：

```python
# A provider-neutral graph definition builder.  The concrete signature varies by
# template but always returns a ProductionGraph ``definition`` dict.
GraphFactory = Callable[..., dict[str, object]]
```

即 `WorkflowTemplateRegistry` 的 `graph_factory`**就是 ProductionGraph 的
definition 生产者**。`director/workflows/` 是**模板目录 + 只读导航**，不是并行执行引擎。

**真实事实——7 个 template_key 分布在 3 个模块：**

| template_key | 定义位置 | 是否被真实生产执行 |
|---|---|---|
| `shot-p0-v1` | `execution/shot_pipeline.py` | **是**（Workbench execution 与 Experiment 的规范 Shot 图） |
| `final-film-v1` | `production/final_film.py` | **是**（成片尾部渲染） |
| `dialogue-post-dub-shot-v1` | `production/templates.py` | 否——仅模板目录内容 |
| `single-character-monologue-v1` | `director/workflows/template_nodes.py` | 否 |
| `two-character-dialogue-v1` | `director/workflows/template_nodes.py` | 否 |
| `action-motion-shot-v1` | `director/workflows/template_nodes.py` | 否 |
| `establishing-reaction-insert-v1` | `director/workflows/template_nodes.py` | 否 |
| `montage-sequence-v1` | `director/workflows/template_nodes.py` | 否 |

**关键事实：真实 Shot 生产只使用一个模板。**
`production/workbench_execution.py:865` 硬编码
`template_key=SHOT_PIPELINE_TEMPLATE_KEY`（`shot-p0-v1`），图定义来自
`shot_pipeline_definition(...)`。5 个 `*-v1` 镜头模板**不参与真实生产**，只被
`api/v1/workflow_planning.py`（规划写入）与 `api/v1/workflow_overview.py`
（只读导航）使用。前端只调用只读的 `workflow-overview`。

**重复代码证据：** `_node()` 助手函数在两个模块中逐字重复
（`director/workflows/template_nodes.py:13` 与 `production/templates.py:11`），
`dialogue_post_dub_definition` 又构建了一份与 `shot-p0-v1` 高度重合的节点/边集合。

**处置建议（Phase 4）：**

| 现状 | 动作 |
|---|---|
| `shot-p0-v1`（唯一真实执行模板） | **KEEP**，并提升为文档中的"规范 Shot Graph" |
| `final-film-v1` | **KEEP** |
| 5 个 `*-v1` 镜头模板 + `dialogue-post-dub-shot-v1` | **KEEP 作为模板目录**，但必须集中到单一模块、共享一个 `_node()` 构造器；并在文档中标注"规划目录，不驱动执行" |
| `director/workflows/` 目录位置 | **RENAME/MOVE**——它是"镜头模板 + 参与计划 + 能力闸门"的目录，不是 Director Runtime 的一部分。其中 `reference_capability` 与 `character_participation` 实际服务 **Production 执行**（见问题 2 的 V-2） |

**明确结论：不得报告"需要消灭第二套 Graph 世界观"——该问题在当前代码中不存在。**

---

### 问题 6：是否存在重复的 Task / Job / Run 概念？

**结论：不存在同义概念泛滥。只有一个需要改名的词。**

`app/**` 中所有继承 `Base` 的模型类，按 `Graph|Flow|Workflow|Job|Task|Run|Node|Operation|Artifact` 模式实测：

```text
director/runtime/models.py :: DirectorRuntimeControl / DirectorRuntimeSignalClaim / DirectorRuntimeWakeup
execution/models.py        :: GraphNode / GraphEdge / Artifact / NodeRun / ProviderOperation
production/models.py       :: ProductionGraph / GraphVersion
providers/models.py        :: ArtifactReferenceToken
```

- **没有** `GenerationTask`、`RenderTask`、`WorkflowTask`、`MediaJob`、
  `VideoJob`、`GenerationRun` 等独立持久化模型。
- "Job" 只出现在非领域层：`workers/jobs.py`（Arq 作业函数命名空间）、
  `FinalFilmJobRead`（成片渲染作业的**读模型**，非独立领域实体）。
- `provider_operation_id` 是远端调用 ID 字段，不是新概念。

**处置：KEEP。** 唯一命名债是 `GenerationService`
（`providers/generation_service.py`）——见问题 8，它虽是"服务名"而非"模型名"，
但读起来像一个平行概念。

---

### 问题 7：是否存在前端绕过统一 Application Command 的入口？

**结论：生产写入路径合规。发现 1 处前端死代码和 1 处 Director 侧旁路。**

**合规证据：** 前端 64 个 API 函数集中在 `frontend/src/lib/api.ts` 统一客户端
（含 CSRF、workspace header、错误解析）。全前端裸 `fetch` 只有 3 处，且都在
`lib/api.ts` 内部（第 49、71、1109 行）——没有散落在 feature 组件中。
生产写入 `POST .../executions` 由 `features/shots/ShotProductionActions.tsx`
发起，服务端经 `api/v1/workbench.py::create_execution` →
`ProductionCommands.submit_user_execution()`，**完全合规**。

**发现 7-a（已解决）：** 前端 `createGeneration()` 死代码已删除；独立生成 HTTP
写入口（`POST`/`GET`/`cancel /api/v1/projects/{id}/generations`）也已退役，
`generations.py` 只保留 capabilities/models/manifest 只读目录。媒体生成的唯一
产品写入口是 Workbench Execution（见问题 8 的结论）。

**发现 7-b（Director 侧旁路，重要）：**
`director/runtime/delegation.py:71` 的 `DirectorRuntimeDelegationService.accept`
**直接实例化** `WorkbenchExecutionService(self._session, user_id=actor.id)` 并自行
重新校验 `plan_fingerprint` 与 `accepted_approximations`（第 76–85 行）。

对照宪法第二节的硬禁令——"Director Runtime **不允许**绕过 Production Runtime
直接创建 NodeRun"与第 2.1 节"决策和委派"的边界：

- 它没有直接写 NodeRun 表，因此**不是最严重形态**；
- 但它**直接持有 Production 的具体服务类**，并复制了
  `ProductionCommands.submit_user_execution()` 的验收校验逻辑，绕开了统一
  Application Command 边界。

**处置：** 这是 Phase 5 的首要收敛点。`delegation.py` 应改为经由
`ProductionCommands`（或一个显式的 ProductionCommand 端口）提交，不得自行
实例化 `WorkbenchExecutionService`，也不得复制指纹/近似值校验。

**前端一级区域现状（Phase 6 输入）：**

| 现状组件 | 当前实际角色 | 建议 |
|---|---|---|
| `ProductionWorkspaceShell`（`components/workstation/ProjectWorkspaceShell.tsx`） | 项目工作区外壳 | KEEP |
| `ProfessionalWorkbench`（`features/production/`） | 生产主视图外壳，内部以 tab 组织 canvas / assets / director / review | KEEP，作为 Production 区域容器 |
| `SceneWorkspace`、`SceneStoryboardWall`（`features/scenes/`） | 场级视图 | KEEP，Production 区域内视图 |
| `DirectorBoard2D`（`features/director/`） | **已是 `ProfessionalWorkbench` 的内部 tab 组件**（`data-testid="director-board-workspace"`、`"director-board-2d"`） | KEEP，**不构成并列产品** |
| `ShotStrip`、`CinematicCanvas`、`ShotProductionActions`（`features/shots/`） | Shot 级组件 | KEEP |
| `MediaReviewCanvas` / `ReviewWorkspace`（`features/review/`） | Review 区域 | KEEP |
| `EditingWorkspace`（`features/editing/`） | Editing 区域 | KEEP |
| `ScriptWorkspace`（`features/script/`） | Creation 区域 | KEEP |
| `WorkflowNavigator`（`features/production/`） | 只读模板导航（消费 `workflow-overview`） | KEEP |

**结论：前端没有 `SceneWorkbench` / `ShotWorkbench` / `CreativeWorkspace` /
`ProductionWorkbench` 这类并列一级产品。** `ShotWorkbench` / `SceneWorkspace`
只作为 **API 名称**存在（`fetchShotWorkbench`、`fetchSceneWorkspace`），是后端
读模型的命名，不是前端产品分层。Phase 6 的真实工作量远小于原方案估计。

---

### 问题 8：是否存在同一业务有多条生产链？

**结论：只有一条生产链，但有 2 个不同的授权入口和 1 个未决表面。**

**唯一生产链的五条来源全部收口到同一个 choke point：**

```text
WorkbenchExecutionService  ← 唯一创建 NodeRun 的各类入口
  ├── api/v1/workbench.py:182            （用户直接命令，经 ProductionCommands）
  ├── director/runtime/delegation.py:71  （Director 委派，⚠ 旁路，见问题 7-b）
  ├── production/repair_service.py:120   （显式修复计划）
  ├── production/application/authorization.py:28 （授权/锁定范围）
  └── production/application/commands.py:72      （ProductionCommands 本体）
```

下游全部收敛：

```text
GraphService.create_graph / materialize_definition
  → NodeRun → Outbox → Arq Worker → execute_media_node_run
  → ProviderOperation → Artifact
```

`GraphService` 的四个调用方也全部收敛到同一条链：
`production/workbench_execution.py:850`、`execution/experiment_nodes.py:227`、
`production/final_film.py:450`、`providers/generation_service.py:367`。

**已决定的表面：** `providers/generation_service.py::GenerationService`。

- 用户可触发的 HTTP 写入口（`POST`/`GET`/`cancel
  /api/v1/projects/{id}/generations`）**已退役**，并由
  `scripts/check_canonical_surface.py` 固定，不能再被注册回来；
- `GenerationService` 作为领域能力**保留**：它复用同一套提交安全机制，不制造
  第二套 NodeRun/ProviderOperation/Artifact 真相；生产代码已无调用方，调用方是
  `tests/unit/test_model_profile_snapshot.py`、`test_model_profiles_api.py`、
  `test_v3_review_fixes.py` 与
  `tests/integration/test_runtime_recovery_matrix_pg.py`。若未来这些测试也消失，
  再连同领域能力一起删除；
- 其自身 docstring 声明 video 能力**有意拒绝**，必须走 Shot 门链。

**不得**在两处同时实现同一业务的 NodeRun 创建——目前已满足该条件。

---

### 附加发现 A：`shared` 层不是叶子层（9 条说明）

矩阵显示 `shared → {director: 3, domain: 5, production: 3, provider: 2}`，
与 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) §二 "shared → 无内部层依赖"冲突。

逐条核实后，**全部是函数内延迟 import（`from ... import` 写在函数体里），不是模块级依赖**：

| 来源 | 目标 | 用途 | 判定 |
|---|---|---|---|
| `shared/db.py` | `access.models`、`execution.models`、`director.turn_models`、`events.models` | RLS 上下文解析与恢复查询（`app.node_run_context(...)`、`director_turn` 状态过滤等） | **语义合理，位置不当** |
| `shared/model_registry.py` | 几乎每一层的 ORM 模型模块 | `load_all_models()`：为独立进程注册完整 SQLAlchemy 模型图，使跨域外键可解析 | **语义合理，位置不当** |

**性质：** 这两者不是"shared 依赖业务"，而是**两个跨层职责被放在了 shared 包里**：

- `db.py` 承担的是 **RLS / 恢复上下文解析**，本质上是一个需要知道各域模型的
  基础设施适配器；
- `model_registry.py` 承担的是 **ORM 元数据引导**，天然需要 import 全部模型。

**处置建议（Phase 2）：** 把 RLS 上下文解析与模型注册引导上移到独立的
`app/bootstrap/`（或 `app/runtime/`），使 `shared` 回到真正的叶子层。
**不得**为了让规则"通过"而删除这两个功能——它们是 RLS 隔离与独立进程启动的硬依赖。

---

### 附加发现 B：`provider !→ production` 规则本身需要细化

见 §3.4 注。`providers/*` 的 6 条出向边指向
`execution/models`、`production/service`、`runtime/scheduler`、`execution/branches`。
其中"Provider 需要持久化 ProviderOperation / Artifact 事实"是**被 production 反向
调用时对数据模型的复用**，不是 Provider 在编排生产。强行反转会制造循环依赖。

**建议：** 把规则细化为

```text
provider !→ production 的业务服务
provider  → execution.models（数据模型）允许
```

---

## 三、模块映射表

`action` 取值：**KEEP** / **RENAME** / **MOVE** / **MERGE** / **DELETE** /
**DECIDE**。`violation` 指向 §二 的问题编号或 NONE。

### 3.1 Director 层

| current_path | current_concept | target_layer | action | violation |
|---|---|---|---|---|
| `director/runtime/`（14 文件 / 2382 行） | Director Runtime Flow、checkpoint、wakeup、ports、executor | director | KEEP | NONE |
| `director/turn_*`、`invocation*`、`inbox*`、`wakeup*` | DirectorTurn / Invocation / Inbox / Wakeup | director | KEEP | NONE |
| `director/proposal_*`、`proposal_commands` | DirectorProposal / Decision 与应用 | director | KEEP | NONE |
| `director/assistant_*`、`context_builder`、`next_action`、`suggestion`、`recommendation` | Director 上下文与建议 | director | KEEP | NONE |
| `director/text_model.py`、`text_transport.py` | 文本推理适配（直接持有 Provider adapter） | director + contract | **RENAME** | **问题 3**（应收敛为 contract 端口） |
| `director/story_generation.py`、`story_proposal.py`、`scene_assembler.py` | Story / Scene 提案生成 | director | KEEP | NONE |
| `director/editing_repair.py`、`editing_suggestion.py` | 成片领域的 Director 建议 | director | KEEP | NONE |
| `director/workflows/`（16 文件 / 2446 行） | 镜头模板目录 + 参与计划 + 能力闸门 | **creative + production** | **MOVE** | **问题 2 (V-2)、问题 5** |
| `director/creative_capabilities/`（15 文件 / 2107 行） | Creative Layer | **creative** | **MOVE**（逻辑已解耦，仅物理迁移） | NONE（问题 1 已证明干净） |
| `director/autonomy_policy.py`、`business_checkpoints.py`、`event_consumer.py` | 自主度策略、业务检查点、事件消费 | director | KEEP | NONE |

### 3.2 Creative 层

| current_path | current_concept | target_layer | action | violation |
|---|---|---|---|---|
| `creative_capabilities/creative_compiler.py` | CreativeIntent（`CompiledCreativeIntent`） | creative | KEEP（Phase 3 决定字段收敛） | NONE |
| `creative_capabilities/visual_bible.py`、`packs.py` | Style → VisualBible | creative | KEEP | NONE |
| `creative_capabilities/shot_language*.py` | ShotLanguage + QualityPolicy | creative | KEEP | NONE |
| `creative_capabilities/skill_library.py`、`contracts.py`、`registry.py`、`composer.py` | Skill 库与解析 | creative | KEEP | NONE |
| `creative_capabilities/packs_library.py`、`pack_registry.py` | Creative Pack | creative | KEEP | NONE |
| `creative_capabilities/creative_templates.py` | 项目启动模板 | creative | KEEP | NONE（被 `access/projects.py` 引用，方向为 domain → creative，允许） |
| `creative_capabilities/freeze.py` | CreativeIntent 冻结与 resume hash | creative | KEEP | NONE |

### 3.3 Production 层

| current_path | current_concept | target_layer | action | violation |
|---|---|---|---|---|
| `production/models.py` | ProductionGraph / GraphVersion | production | KEEP | NONE |
| `production/service.py` | GraphService（图创建/物化/发布） | production | KEEP | NONE |
| `production/workbench_execution.py` | **唯一 NodeRun 创建 choke point** | production | KEEP | NONE |
| `production/execution_plan.py` | WorkbenchExecutionPlan（冻结计划） | production | KEEP | NONE |
| `production/application/`（authorization / commands / events / facts） | Application Command 边界 | production | KEEP（作为合规范板） | NONE |
| `production/formal_selection.py` | Candidate / Formal | production | KEEP | NONE |
| `production/repair_service.py` | Repair 显式计划 | production | KEEP | **问题 2 (V-2)** |
| `production/golden_project.py` | Golden project 种子/fixture | production | **MOVE**（移至测试或工具位置） | **问题 2 (V-3)** |
| `production/experiment_service.py`、`models.py::ExperimentBranch` 等 | Experiment 隔离分支 | production | KEEP | NONE |
| `production/final_film.py`、`timeline_renderer.py`、`timeline_subtitles.py` | Final Film（MP4 + SRT） | production + domain/editing | KEEP | NONE |
| `production/reference_intents.py` | `ShotReferenceIntent`（被 contract 反向引用） | **contract** | **MOVE** | **问题 2 (V-1)** |
| `production/templates.py` | `dialogue-post-dub-shot-v1` 图定义 | production | **MERGE**（合并进统一模板模块） | 问题 5 |
| `execution/models.py` | GraphNode / NodeRun / ProviderOperation / Artifact | production | KEEP | NONE |
| `execution/product_path.py`、`voice_path.py` | 统一媒体执行 | production | KEEP | **问题 2 (V-2 引用面)** |
| `execution/shot_pipeline.py` | `shot-p0-v1` **规范 Shot Graph** | production | KEEP（提升为规范） | NONE |
| `execution/artifact_lineage.py` | Artifact 身份与血缘不变量 | production | KEEP | NONE |
| `execution/shot_locks.py`、`branches.py`、`composite_media.py`、`experiment_nodes.py`、`runtime_invariants.py` | Shot 锁、实验节点、合成、不变量 | production | KEEP | NONE |
| `runtime/scheduler.py` | Outbox / NodeRun 调度 | production | KEEP | NONE |
| `workbench/shot_service.py` | Shot workbench 服务 | production + **director** | **RENAME** | **问题 2 (V-4)** |
| `workbench/scene_service.py`、`workspace_state_service.py` | 场与工作区状态 | production | KEEP | NONE |

### 3.4 Provider 层

| current_path | current_concept | target_layer | action | violation |
|---|---|---|---|---|
| `providers/manifest.py`、`capabilities.py`、`contracts/` | ModelManifest / Capability / Provider 契约 | provider | KEEP | NONE |
| `providers/model_profiles/`（含 `slots.py`、`node_snapshot.py`） | ModelSlot 与能力映射 | provider | KEEP | NONE |
| `providers/registry.py`、`router.py`、`runtime.py`、`selection.py`、`model_resolution.py` | 注册、路由、运行时、选择 | provider | KEEP | NONE（但被 Director 直接 import，见问题 3） |
| `providers/generation_service.py` | 单节点生成域（无 HTTP 写入口） | provider | KEEP（HTTP 写面 RETIRED） | **问题 8 已决定** |
| `providers/connection_service.py`、`workspace_credentials.py`、`idempotency.py`、`execution_identity.py` | 连接、凭据、幂等、执行身份 | provider | KEEP | NONE |
| `providers/reference_delivery.py` | 引用字节投递 | provider | KEEP | 需确认不与 provider → production 规则冲突（见下注） |
| ~~`providers/fake.py`~~ | 假 Provider 测试替身 | provider | **已删除** | 无调用方；未来测试 fixture 放 `backend/tests` |

> **注：** `providers/*` 有 6 条指向 `app.execution.*` / `app.production.*` /
> `app.runtime.*` 的边（`connection_service`、`generation_service`、
> `reference_delivery`）。按 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) §三
> `provider !→ production` 属违规方向，但性质是"Provider 需要持久化
> ProviderOperation/Artifact 事实"——即 provider 被 production 反向调用时复用其
> 模型。**处置：Phase 2 决定是 (a) 收紧为只依赖 `execution/models` 这一数据层，
> 还是 (b) 把 `provider !→ production` 规则细化为"禁止依赖 production 的
> 业务服务，允许依赖 `execution.models` 数据模型"。建议 (b)，因为强行反转会制造
> 循环。这是本次盘点发现的**规则本身需要细化**之处。**

### 3.5 Domain / Contract / Shared 层

| current_path | current_concept | target_layer | action | violation |
|---|---|---|---|---|
| `contracts/production_commands.py`、`production_facts.py`、`domain_events.py`、`director_runtime.py` | 共享契约 | contract | KEEP | **问题 2 (V-1)**（等待 `ShotReferenceIntent` 迁入） |
| `access/models.py`、`projects.py` | Project / Workspace / CreativeProfile | domain | KEEP | **`access/projects.py:19` 有 1 条模块级 `→ creative_capabilities.creative_templates` import（问题 1 / V-6）** |
| `assets/models.py`、`scene_service.py`、`version_service.py`、`script_import.py` | Scene / Shot / Asset | domain | KEEP | NONE（`scene_service` 有 1 条局部 `ExperimentBranch` import，影响面报告用，可接受） |
| `consistency/` | identity / continuity / drift 证据 | domain | KEEP | NONE |
| `delivery/models.py`、`download.py` | Review 标注与导出 | domain | KEEP | NONE |
| `editing/`（5 文件 / 504 行） | EditSession / Timeline | domain | KEEP | NONE |
| `shared/`、`events/`、`security/`、`storage/` | 基础设施原语 | shared | KEEP | NONE |
| `workers/`（7 文件 / 602 行） | Arq 入口 | frontend | KEEP | NONE |
| `api/`（36 文件 / 8199 行） | HTTP 表面 | frontend | KEEP | NONE |

---

## 四、Phase 2–7 的实际工作量修正

基于以上实测，原执行方案的难度估计需要修正：

| Phase | 原方案假设 | 实测结论 |
|---|---|---|
| **Phase 2** Creative Layer 解耦 | 需要拆依赖、可能需要 facade 过渡 | **依赖已解耦**。工作量 = 物理目录迁移决策 + 依赖 Gate。7 条 director → provider 文本推理边 + 4 条 production → director 边才是真正要处理的对象 |
| **Phase 3** CreativeIntent Contract | 需要"新建" CreativeIntent | **已存在** `CompiledCreativeIntent`。真实任务是决定是否把嵌套 patch 结构收敛为 canonical 顶层字段表，并定义版本化/持久化/来源记录 |
| **Phase 4** ProductionGraph 收敛 | 需要删除/降级大量滥用 Node | **Node 无滥用**（10 个全部 KEEP）。真实任务是① 统一 3 个模块中的模板目录；② 消除 `_node()` 重复；③ 成形 Production Planner 以支持自动最小重算 |
| **Phase 5** 入口统一 | 需要清查大量旁路 | 生产写入路径**已合规**。① `director/runtime/delegation.py:71` 旁路仍待处理；② `GenerationService` 已决定：HTTP 写面退役、领域能力保留 |
| **Phase 6** 前端收敛 | 需要拆多个并列工作台 | **无并列一级产品**。`DirectorBoard2D` 已是内部 tab。真实任务主要是命名与文档对齐 |
| **Phase 7** 验证与防回归 | 需要新写依赖测试 | 需要，且应立即做——因为 Phase 2–6 的改动面比预期小，**依赖 Gate 是防止未来回归的主要价值** |

**总判断：** 当前代码的"缝合怪感"主要来自**物理目录布局与文档缺失**，
而不是**逻辑依赖混乱**。因此最高性价比的下一步是
**Phase 7 的依赖 Gate + Phase 2 的物理收敛**，而非大规模重写。

---

## 五、本轮遗留的待决问题

以下问题本轮**未决定**，需在进入 Phase 2 前由 Owner 确认：

1. `director/creative_capabilities/` 是否物理迁移到 `app/creative/`？
   （依赖已干净，迁移是纯目录收益，风险来自 30+ 处 import 与 generated OpenAPI 稳定性）
2. `ShotReferenceIntent` 迁入 `app/contracts/` 是否接受一次契约层新增？
3. `provider !→ production` 规则是否按 §3.4 注细化为"允许依赖 `execution.models`"？
4. `director/workflows/` 中的 `reference_capability` / `character_participation`
   迁往何处（creative 还是 production）？
5. `production/golden_project.py` 迁往测试工具位置是否影响现有证明脚本
   （`scripts/prove_*.py`）？
6. `domain → creative`（`access/projects.py → creative_templates`）是改为由
   application 层注入模板查找，还是正式声明为允许例外？
7. `shared/db.py` 的 RLS 上下文解析与 `shared/model_registry.py` 的模型引导是否
   上移到新包，使 `shared` 回到叶子层？
8. [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) §三 的
   `provider !→ production` 是否按附加发现 B 细化？
