# DOMAIN_VOCABULARY — 术语唯一解

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Date: 2026-09-15 / Base: dev 5ea45d6 / Alembic head: 20260910_0066

本文件是 DramaForge 的**唯一词典**。任何模块、PR、Review、文档只能使用这里的词。

规则：

1. 每个词在此处**只有一个含义**，并给出当前代码锚点。
2. 想表达的意思不在下表 → 先在本文件补词条，再写代码；不得临时造词。
3. 同一含义已有词条 → 禁止新增同义词。
4. 世界观与依赖约束见
   [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) /
   [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md)；
   Graph 细节见 [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md)。

---

## 一、产品实体

| 术语 | 唯一含义 | 代码锚点 |
|---|---|---|
| **Workspace** | 顶层租户/空间容器，所有 Project 归属它 | `access/models.py::Workspace` |
| **Project** | 一部作品；主链的起点，所有生产事实的项目范围 | `access/models.py::Project` |
| **Creative Profile** | 每个 Project 唯一一份的创作档案：启动方式、导演自主度、选中的类型/风格/技能/镜头语言 | `access/models.py::ProjectCreativeProfile`（`project_creative_profiles`，`project_id` unique） |
| **Story** | 故事层内容，由 Director 提案产生，用户显式 Apply 后成为事实 | `director/story_proposal.py`、`director/story_generation.py` |
| **Script** | 剧本文档；导入或生成的脚本事实 | `assets/models.py::ScriptDocument`、`assets/script_import.py` |
| **Episode** | 剧集容器，Scene 的父级 | `assets/models.py::Episode` |
| **Scene** | 场；Shot 的容器，带场景级空间与影响面报告 | `assets/models.py::Scene`、`assets/scene_service.py` |
| **Shot** | 镜头；**生产的最小单位**，ProductionGraph 的 `scope_type="shot"` 对应实体 | `assets/models.py::Shot` |
| **Asset** | 可复用创作资产（角色、场景、道具等） | `assets/models.py::Asset` |
| **AssetVersion** | Asset 的一次不可变版本；身份引用只认版本 | `assets/models.py::AssetVersion` |
| **AssetVersionReference** | Shot/Production 对某个 AssetVersion 的显式身份引用——**唯一身份引用源**，不存在 Character/CharacterReference 兼容层 | `assets/models.py::AssetVersionReference` |
| **Candidate** | 生产出来但未被用户选定的结果。**没有 Candidate 表**：候选直接从 NodeRun + Artifact 派生 | `production/formal_selection.py::list_formal_candidates` |
| **Formal** | 用户显式确认后的正式结果。Keyframe 与 Video 各记录一个正式 Artifact 引用 | `production/formal_selection.py::set_formal_keyframe` / `set_formal_video` / `require_formal_keyframe`；列为 `Shot.formal_keyframe_artifact_id`、`Shot.formal_video_artifact_id` |
| **Experiment** | 隔离的 Shot 实验分支与采纳；**复用同一图引擎，不是第二条生产链** | `production/models.py::ExperimentBranch`、`production/models.py::ProductionExperiment`、`production/models.py::ShotExperiment`、`production/experiment_service.py` |
| **Review** | 对生产结果的标注与决策；只读生产事实、只写评审事实 | `delivery/models.py::ReviewAnnotation`、`production/service.py` |
| **Repair** | 有证据的显式修复计划，绝不静默重跑 | `production/repair_service.py` |
| **EditSession** | 剪辑会话及其 timeline 版本（成片领域） | `editing/models.py::EditSession`、`editing/timeline_builder.py` |
| **FinalFilm** | 绑定 timeline 版本渲染出的成片交付（MP4 + SRT）。**不是独立持久化实体**，是 `final-film-v1` ProductionGraph 的渲染结果读模型 | `production/final_film.py`（`FinalFilmRead`、`queue_final_film_render`）、`production/timeline_renderer.py`、`production/timeline_subtitles.py` |
| **Export** | 对外导出记录与条目 | `delivery/models.py::Export`、`delivery/models.py::ExportItem` |

---

## 二、Creative Layer

Creative Layer 是普通领域能力与编译能力的集合，**不是 Runtime**。

| 术语 | 唯一含义 | 代码锚点 |
|---|---|---|
| **Creative Layer** | Style / Skill / Pack / VisualBible / ShotLanguage / Resolver / Compiler 的总称；无 Worker、无 Queue、无 Checkpoint、无独立生命周期 | 当前物理位置 `director/creative_capabilities/`（逻辑边界见宪法第三节） |
| **Style** | 回答"作品应该长什么样"；产出 VisualBible | `creative_capabilities/packs.py::StylePackSpec` |
| **StylePack** | Style 的打包与冻结载体（key + version + contract_hash） | `creative_capabilities/packs.py`、`packs_library.py` |
| **Skill** | 回答"这类创作任务该怎么做"；只提供适用条件、专业规则、输入要求、输出结构、质量约束、常见失败处理。**不调 Provider、不创建 Worker、不保存 Runtime 状态、不直接生成 Artifact** | `creative_capabilities/contracts.py::CreativeSkillSpec`、`CreativeSkillStack`、`skill_library.py` |
| **Creative Pack** | Style + Skills + Defaults + Quality Rules 的**预设组合**，不引入新的执行机制 | `creative_capabilities/packs.py`、`packs_library.py`、`pack_registry.py` |
| **Genre Profile** | 类型片默认（故事节奏、场景节奏、对白密度、钩子策略、反转频率、镜头节奏） | `creative_capabilities/packs.py::GenreProfileSpec` |
| **VisualBible** | Style 编译后的视觉圣经补丁：色彩、光线、材质、镜头倾向、构图规则、环境氛围、后期质感 | `creative_capabilities/packs.py::VisualBiblePatch`、`visual_bible.py::VisualBibleCompiler` |
| **ShotLanguage** | 镜头语言包：景别、角度、镜头意图、运动、构图、覆盖、反应规则、剪辑规则、连续性 | `creative_capabilities/shot_language.py::ShotLanguagePackSpec`、`ShotDirectorIntentPatch`、`shot_language_compiler.py` |
| **Quality Policy** | 质量维度与失败分类（TECHNICAL_BLOCKER / QUALITY_WARNING / HUMAN_JUDGMENT） | `creative_capabilities/shot_language.py::QualityPolicySpec`、`QualityDimension` |
| **Skill Resolver** | 按适用条件从 Skill 库解析出应生效的 Skill 组合 | `creative_capabilities/skill_library.py`、`registry.py`、`composer.py` |
| **Creative Compiler** | 把用户意图 + 项目上下文 + Genre + SkillStack + Style + ShotLanguage + QualityPolicy 确定性编译成一份冻结的 CreativeIntent | `creative_capabilities/creative_compiler.py::CreativeCapabilityCompiler` |
| **CreativeIntent** | **前段创意系统与后段 Production 之间的唯一中间协议**。代码名为 `CompiledCreativeIntent`，`frozen=True`。字段表与实现差异见宪法第四节 | `creative_capabilities/creative_compiler.py::CompiledCreativeIntent` |
| **CreativeIntent freeze** | 把 CreativeIntent 及其 pack 身份序列化，保证 resume 使用同一组 hash | `creative_capabilities/freeze.py` |
| **Creative Template** | 项目启动模板（`start_type="TEMPLATE"` 时引用），贡献 Genre/Style/Skill 预设；**只是项目初始化方式** | `creative_capabilities/creative_templates.py`、`access/projects.py` |
| **Model Adaptation** | 把 CreativeIntent + ModelCapability 编译为 `EffectiveProviderRequest` 的能力 `[未落地：当前由 Provider layer 的 compiler/runtime 承担]` | 参见 `providers/` |

**优先级门（Creative 域唯一权威，不得改写）：**

```text
explicit user value > accepted proposal > project override > pack default
```

实现于 `creative_compiler.py::CreativeCapabilityCompiler.compile`。Pack 只提供默认值：
用户或项目已显式选择时，pack 默认值**不得**被应用。

---

## 三、Director

| 术语 | 唯一含义 | 代码锚点 |
|---|---|---|
| **Director Runtime** | 提案式编排 Runtime：理解、推理、建议、等待、恢复、决策、委派；**不拥有媒体** | `director/runtime/`、`workers/director.py` |
| **Director Runtime Flow** | Director Runtime 的内部控制流。**不叫 DirectorGraph**。内部由 LangGraph 实现，但 LangGraph 不作为领域概念暴露 | `director/runtime/langgraph_adapter.py` |
| **DirectorThread** | 导演会话线程 | `director/assistant_models.py::DirectorThread` |
| **DirectorMessage** | 线程中的一条消息 | `director/assistant_models.py::DirectorMessage` |
| **DirectorTurn** | 一次有界的导演轮次（有状态、可恢复、可 fencing） | `director/turn_models.py::DirectorTurn`、`turn_service.py` |
| **DirectorInvocation** | 一次具体的 LLM 调用事实及其证据 | `director/invocation_models.py::DirectorInvocation`、`invocations.py` |
| **DirectorProposal** | 结构化提案（含 ProposalItem）；用户 Apply 后才成为事实 | `director/proposal_models.py::DirectorProposal`、`DirectorProposalItem`、`proposal_service.py` |
| **DirectorDecision** | 用户对提案的显式决定（Apply / Save / Formal / Export 用户门） | `director/proposal_commands.py` |
| **DirectorInbox** | 传给导演的事件收件箱 | `director/inbox_models.py::DirectorInbox`、`inbox.py` |
| **DirectorWakeup** | 唤醒导演的信号（含重放） | `director/inbox_models.py::DirectorWakeup`、`wakeup.py`、`wakeup_replay.py` |
| **Director autonomy** | AUTO / ASSIST / MANUAL：**只是 Director 参与模式**，不创建第二条生产链 | `director/autonomy_policy.py`、`ProjectCreativeProfile.director_autonomy` |
| **Checkpoint** | Director 轮次的可恢复检查点 | `director/runtime/checkpoint.py`、`business_checkpoints.py` |

**用户门（不可绕过）：** Apply / Save / Formal / Export。Director 自主度任何时候都
不得绕过这四个显式用户门。

---

## 四、Production

| 术语 | 唯一含义 | 代码锚点 |
|---|---|---|
| **Production Runtime** | 统一媒体执行 Runtime：可靠执行已确定的生产意图 | `production/`、`execution/`、`runtime/scheduler.py`、`workers/` |
| **ProductionCommand** | 进入 Production Runtime 的显式命令契约 | `contracts/production_commands.py`、`production/application/commands.py` |
| **ProductionGraph** | 为完成一次生产任务需要执行哪些生产步骤及其依赖关系。项目执行图，可版本化。领域内 `Graph` 默认只指它 | `production/models.py::ProductionGraph` |
| **GraphVersion** | ProductionGraph 的一个版本（草稿/已发布，带 definition_hash） | `production/models.py::GraphVersion` |
| **GraphNode** | Graph 版本内的一个节点实例 | `execution/models.py::GraphNode` |
| **GraphEdge** | Graph 版本内的节点依赖边 | `execution/models.py::GraphEdge` |
| **Node** | ProductionGraph 内一个有明确输入和输出的**生产步骤定义**。不是普通函数 | 持久化节点类型见 [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md) 第三节 |
| **NodeRun** | 某个 Node 的**一次实际执行事实**（排队 → 运行 → 终态）。同一个 Node 的多次重做是多个 NodeRun | `execution/models.py::NodeRun` |
| **ProviderOperation** | 一次真实的外部模型/API 调用事实。**只有 NodeRun 一个 owner**，关系为 `NodeRun 1..N ProviderOperation` | `execution/models.py::ProviderOperation` |
| **Artifact** | 不可变产物及其血缘 | `execution/models.py::Artifact`、`execution/artifact_lineage.py` |
| **Outbox** | 事务性事件外发与死信 | `events/`、`workers/dispatcher.py` |
| **WorkbenchExecutionPlan** | 冻结的执行计划：模型身份、引用编译、阶段与节点契约在提交前被显式冻结 | `production/execution_plan.py::WorkbenchExecutionPlan` |
| **ShotHumanLock** | Shot 级人工锁，防并发执行冲突 | `execution/shot_locks.py` |
| **Production Planner** | Production Runtime 内部逻辑角色：由 CreativeIntent + 现有 Artifact + Formal 状态 + ModelCapability + 修改范围推导**最小** ProductionGraph。它不负责创意 `[部分落地：`production/execution_plan.py` 冻结阶段契约；完整最小重算规划器尚未独立成形]` | `production/execution_plan.py`、`production/workbench_execution.py` |

---

## 五、Provider

| 术语 | 唯一含义 | 代码锚点 |
|---|---|---|
| **Provider** | Production Runtime 的外部执行能力。**不是 Runtime**，无 Worker/Queue/Checkpoint | `providers/` |
| **ModelManifest** | 模型能力冻结身份：能力、输入槽、轮询规格等。无静默回退 | `providers/manifest.py::ModelManifest`、`InputSlotSpec` |
| **ModelCapability** | 模型声明的能力与输入槽约束 | `providers/capabilities.py::Capability`、`providers/manifest.py` |
| **ModelSlot** | 语义槽位到模型能力的映射 | `providers/model_profiles/slots.py::ModelSlot`、`node_snapshot.py::NODE_SLOT_MAP` |
| **ProviderConnection** | 用户 BYOK 连接及其修订 | `providers/models.py::ProviderConnection`、`connection_service.py` |
| **EffectiveProviderRequest** | CreativeIntent + ModelCapability 编译后的最终 Provider 请求 | `providers/` compiler/runtime（`unified-v1`） |
| **ArtifactReferenceToken** | 提供给 Provider 的临时引用令牌（不泄露凭据） | `providers/models.py::ArtifactReferenceToken`、`reference_delivery.py` |

---

## 六、Repository / 运行时词汇

| 术语 | 唯一含义 | 代码锚点 |
|---|---|---|
| **Dispatcher** | 常驻事务性 Outbox 分发进程 | `workers/dispatcher.py` |
| **Worker** | Arq 执行进程：`worker-default` / `worker-director` / `worker-heavy` | `workers/default.py`、`director.py`、`heavy.py` |
| **Canonical surface** | 已退役并被质量门硬禁止回归的表面 | `scripts/check_canonical_surface.py`、[ARCHITECTURE.md](ARCHITECTURE.md) 退役边界节 |

---

## 七、禁止的同义词

以下词**不得**再作为领域概念引入。若本质属于已有词条，必须使用既有词条名。

| 禁止新增 | 应使用 |
|---|---|
| `GenerationTask`、`RenderTask`、`WorkflowTask`、`MediaJob`、`VideoJob`、`GenerationRun`、`GenerationService`（作为新概念） | **NodeRun** |
| `ProviderCall`、`ModelCall`、`ApiCall` | **ProviderOperation** |
| `DirectorGraph`、`CreativeGraph`、`SkillGraph`、`EditingGraph`、`UIWorkflowGraph` | **Director Runtime Flow**（控制流）或 **ProductionGraph**（执行计划） |
| `ProductionWorkbench`、`CreativeWorkspace`、`SceneWorkbench`、`ShotWorkbench`、`DirectorBoard`（作为一级产品区域） | 一级区域只保留 **Project Lobby / Creation / Production / Editing**；上述名称最多只能是 Production 区域**内部组件或视图** |
| `CreativeRuntime`、`SkillRuntime`、`StyleRuntime`、`EditingRuntime` | 禁止存在；Creative Layer 是能力集合，Editing 属于成片领域 |
| `Character`、`CharacterReference`（兼容层） | **AssetVersionReference** |
| `Quick Creation`、`V1 Workbench`、`Professional`（作为并列产品） | 只有一个产品主链 |

**已存在的同义风险（历史遗留，需在后续 Phase 消除，见
[ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md)）：**

| 词 | 现状 | 处置 |
|---|---|---|
| `Experiment`（`ExperimentBranch` / `ProductionExperiment` / `ShotExperiment`） | 三个类名并存，语义分层合理但命名易混 | KEEP，但必须在文档中固定为"Experiment = 隔离的 Shot 分支" |
| `Node` 与 `GraphNode` | `Node` 是概念，`GraphNode` 是持久化实例 | KEEP，成对使用 |
| `Workflow` | 仅存在于 `director/workflows/`，指"镜头生产模板目录" | RENAME/MERGE，见映射文档 |
