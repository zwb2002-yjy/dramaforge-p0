# CANONICAL_ARCHITECTURE — DramaForge 架构宪法

Status: current（入口见 [CURRENT.md](CURRENT.md)）
迁移状态统一见 [DATA_MODEL.md](DATA_MODEL.md)。

本文件定义 DramaForge **以后所有模块必须服从的架构世界观**。它是"宪法"，只回答
"这个系统到底是什么、一个新模块应该归属哪里"。

与其他文档的分工（不要互相重复）：

| 文档 | 只回答 |
|---|---|
| [CURRENT.md](CURRENT.md) | 当前哪些文档是权威的（索引） |
| **本文件** | DramaForge 整体到底是什么（宪法 / 目标世界观） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 当前实际系统结构和组件实现（组织结构图） |
| [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md) | Production Runtime 怎么跑 |
| [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md) | Graph / Node / NodeRun 怎么定义与组织执行计划 |
| [DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md) | 项目里的词只能是什么意思 |
| [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) | 模块之间谁能依赖谁 |
| [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) | 当前代码 → 目标架构的映射与差距 |

**当前实现事实以代码、迁移、测试和运行证据为准。** 本文件定义长期架构原则；
当前差距、待决设计与迁移任务归 ARCHITECTURE_MAPPING，不把参考方案当作必须实施的任务。
规则冲突须诊断，不能把错误实现改写成目标行为。验证与记录方式归 DEVELOPMENT，
宪法不要求每次编辑运行全量测试、创建报告、增加抽象层或迁移目录。

---

## 一、只有一条产品主流程

**产品路径的 canonical 定义在 [CREATION_FLOW.md](CREATION_FLOW.md)。** 下表是同一主链的
**概念层摘要**（13 个概念节点），不是第二条路径；CURRENT / PRODUCT / RELEASE 中的
主链句也只是摘要。

```text
Project
  ↓
Creative Profile
  ↓
Story / Script
  ↓
Scene
  ↓
Shot
  ↓
Director
  ↓
CreativeIntent
  ↓
Production
  ↓
Candidate
  ↓
Formal
  ↓
Review / Repair
  ↓
Editing
  ↓
Final Film
```

以下内容**不是**独立主流程，只是主链上的模式或能力：

| 概念 | 真实身份 |
|---|---|
| Template Start / Free Start | 项目初始化方式 |
| AUTO / ASSIST / MANUAL | Director 参与模式 |
| Style / Skill / Creative Pack | Creative Layer 的创作能力 |
| Provider | Production Runtime 的外部执行能力 |
| Editing | 成片领域，不建立新 Runtime |
| Repair | 重新形成 CreativeIntent / ProductionCommand 后回到 Production |
| Experiment | 隔离的 Shot 分支，复用同一图引擎，不是第二条生产链 |

创作与生产能力应服务于这条主链，不建立第二条生产事实链。十三个节点是概念摘要，
不要求每个请求依次经过所有节点，也不要求每个新功能新增对应模块。
账号、连接配置、安装、运维和工程工具属于支持能力，按自身领域合同工作；它们不需要
包装成 CreativeIntent 或生产任务。新增产品范围仍由当前用户任务与产品权威决定。

---

## 二、只有两个 Runtime

DramaForge 只有两个拥有创作或生产业务生命周期的 Runtime。Worker 进程数、队列数、
第三方 SDK 中的 runtime 类和基础设施服务数不等于业务 Runtime 数。

### 2.1 Director Runtime

```text
用户输入
  ↓
加载项目事实
  ↓
调用 LLM
  ↓
形成 Proposal / NextAction
  ↓
等待用户或生产结果
  ↓
恢复 / 继续
```

归属内容：

```text
DirectorThread / DirectorMessage / DirectorTurn
DirectorInvocation
DirectorInbox / DirectorWakeup
Checkpoint
Director Worker
Director Runtime Flow（内部由 LangGraph 实现）
```

Director Runtime **只负责**：

> 理解、推理、建议、等待、恢复、决策和委派。

Director Runtime **不允许**：

- 直接调用媒体 Provider；
- 直接创建 Artifact；
- 绕过 Production Runtime 直接创建 NodeRun；
- 把 Provider 参数写死在 Director 逻辑内；
- 绕过 Apply / Save / Formal / Export 用户门。

当前实现见 [DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md)。
当前代码的越界点见 [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md)。

### 2.1.1 持续目标与业务流程监督（目标架构，尚未实施）

机构版目标架构在 Director Runtime 之上增加 MasterRun 监督记录，并以 BusinessFlow
表达可跨多个 DirectorTurn 推进的业务流程。它们是业务事实和控制合同，不构成第三个 Runtime。

- **MasterRun**：用户明确建立的持续创作目标及其监督身份，可跨多个有界 DirectorTurn、
  BusinessFlow、用户等待和外部生产任务。普通问答/进度查询不自动创建 MasterRun。
- **MasterRunPlanRevision**：MasterRun 的不可变计划版本。计划确认只确认目标范围和流程安排，
  不自动创建 NodeRun、授权付费生产、Formal 或 Export。
- **DirectorTurn**：仍是一次有界推理/推进；不升级为长期目标，不改变现有 Turn 状态机、
  request_key、scope 或引擎身份。
- **BusinessFlow**：业务流程定义/实例/步骤。首期由版本化 Python LangGraph Graph 代码注册；
  LangGraph 仍是现有唯一 Director 执行引擎，不为 MasterRun 创建根图、第二套 Agent Loop
  或通用数据驱动 DAG 解释器。
- **LangGraph Thread / Checkpoint**：只保存图执行位置和恢复快照，不替代 DirectorThread、
  MasterRun、BusinessFlow 或正式业务数据。
- **Production Runtime**：继续独占 NodeRun、ProviderOperation、Artifact 等生产事实；
  BusinessFlow 通过现有生产命令/回执合同提交和观察生产任务。

MasterRun Supervisor 是 Director 逻辑控制能力，不是常驻的第三 Runtime。它通过短事务管理
目标、计划版本、监督关系和事件唤醒；需要模型判断时启动有界 DirectorTurn。不得持有跨网络
长事务，不直接调用媒体 Provider，不复制 Production 状态。


### 2.2 Production Runtime

```text
ProductionCommand
  ↓
ProductionGraph
  ↓
NodeRun
  ↓
Outbox / Worker
  ↓
ProviderOperation
  ↓
Artifact
```

归属内容：

```text
ProductionGraph / GraphVersion / GraphNode / GraphEdge
NodeRun
Outbox
Arq Worker
ProviderOperation
Artifact
重试、幂等、恢复、异步执行
```

Production Runtime **只负责**：

> 如何可靠执行已经确定的生产意图。

Production Runtime **不允许**：

- 自己调用 Director LLM 决定创作方向；
- 自己选择 Style / Skill；
- 自己解释用户自然语言意图；
- 把 Director 业务重新复制到 Production 内。

当前实现见 [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md)。

### 2.3 禁止第三 Runtime

明确禁止新建：

```text
Skill Runtime
Style Runtime
Editing Runtime
Creative Runtime
Provider Runtime（作为独立生命周期服务）
```

媒体 Provider adapter 是 Production Runtime 的外部 I/O 适配，不另建应用内的业务
Worker、队列、Checkpoint 或生产恢复链。外部供应商的任务状态、轮询和下载由既有
执行链接管，不因协议名称含 Runtime 而删除。Director 的文本推理访问按
MODULE_BOUNDARIES §4.3 的契约端口边界执行，不构成第三 Runtime。

---

## 三、Creative Layer 的定位

Creative Layer 是**一组普通领域能力和编译能力**，不是 Runtime。

```text
Creative Layer
├── Style
├── Skill
├── Creative Pack
├── VisualBible
├── ShotLanguage
├── Skill Resolver
├── Creative Compiler
├── Model Adaptation
└── CreativeIntent Contract
```

Creative Layer：

- 没有自己的 Worker；
- 没有 Queue；
- 没有 Checkpoint；
- 没有独立生命周期；
- 不新增 Skill Runtime；
- 不新增 Style Runtime；
- 不知道具体 Runtime 的存在。

逻辑边界不由目录名称决定。Creative Layer 应能在不启动 Director Runtime 的前提下
解析 Style、解析 Skill、编译 VisualBible、编译 ShotLanguage、生成/验证 CreativeIntent。
当前物理位置与真实越界见 ARCHITECTURE_MAPPING §2、§4；整理任务不自动授权搬迁目录。

---

## 四、CreativeIntent 是唯一创意语义中间协议

Creative Layer 向生产编译传递的创意语义以 CreativeIntent 为唯一合同，不另造一份
同义创意事实。经用户确认的内容及来源可冻结到既有领域事实，再由生产编译消费；
不要求所有 API、Command、队列消息和 Provider 请求都使用同一个 DTO。

各合同分别承担独立职责：

| 合同 | 职责与边界 |
|---|---|
| CreativeIntent | 已解析的创意语义、优先级与来源，不承担执行授权或任务状态 |
| Director / Production Command | 显式业务操作、权限及幂等入口，不替代创意事实 |
| ExecutionPlan / 冻结模型计划 | 将已确认内容落实为可执行步骤、引用和精确执行身份 |
| EffectiveProviderRequest | 按 ModelManifest 编译的供应商请求；不得重新选择或解释 Style / Skill |
| NodeRun / ProviderOperation / Artifact | 执行、外部调用与产物事实，不反向改写创意决定 |

Provider 消费确定的执行请求。CreativeIntent 与模型能力参与生产编译，不要求 Provider
直接 import Creative 编译器；Director 文本推理及账号/连接管理也不强制套用媒体创意协议。

### 4.1 当前合同与实现入口

CreativeIntent 在代码中**已经存在**，名称是 `CompiledCreativeIntent`：

```text
backend/app/director/creative_capabilities/creative_compiler.py
    class CompiledCreativeIntent(BaseModel)   # frozen=True, extra="forbid"
```

它现在的字段是：

| 字段 | 含义 |
|---|---|
| `story_guidance` | 类型片默认给出的故事节奏/钩子指导 |
| `visual_bible_patch` | Style 编译出的 `VisualBiblePatch`（`patches` 内按 lighting / contrast / texture / lens_language / composition / camera_behavior / motion_feel / production_design / post_processing / palette 分键，仅填充项目未显式设置的字段） |
| `shot_director_intent_patch` | ShotLanguage 编译出的 `ShotDirectorIntentPatch`（shot_size / camera_angle / lens_intent / camera_motion / composition / focus_strategy / coverage / reaction_rule / cutting_rule / continuity） |
| `effective_values` | 优先级门之后的有效值全集 |
| `value_sources` | 每个叶子值的来源（pack_default / project_override / accepted_proposal / user_confirmed） |
| `overridden_defaults` | 被显式选择覆盖掉的 pack 默认值 |
| `skill_guidance` | 命中的 Skill 契约摘要 |
| `workflow_hints` | 类型片 workflow 偏好 |
| `reference_guidance` | Style 给出的参考建议 |
| `quality_hints` | 质量约束提示 |
| `provenance` | 冻结的 pack 身份（genre / skills / style / shot_language / quality_policy 的 key + version + contract_hash） |

创意值优先级的唯一规则见 [DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md) 的优先级门；
这里不再维护第二份顺序定义，编译行为须与该规则一致。

### 4.2 表达形式不等于新增架构义务

唯一创意语义合同不要求把现有嵌套字段改成平铺字段，也不要求建立第二份 schema。
历史执行方案的字段布局是设计参考，不是当前迁移命令。是否调整结构须有具体用例、
消费者和迁移收益，按规则变更流程处理；待决项统一记录在 ARCHITECTURE_MAPPING。

### 4.3 参考意图已在契约层定义

`ShotReferenceIntent` 定义在 `backend/app/contracts/shot_reference.py`，承担
"引用身份而非 prompt 兜底"的语义（"deliberately carries identity rather than
name/prompt fallback"），并由 `CreativeIntent` 侧编译进 ProductionCommand。

contracts → production 的反向依赖已移除。生产编译器直接引用契约类型，
`backend/app/contracts/shot_reference.py` 是唯一类型定义与唯一导入入口，不保留重新导出。

---

## 五、Graph 只有一个：ProductionGraph

领域文档中的 `Graph` **默认且只**指 ProductionGraph。

- 产品主流程（Project → Story → Scene → Shot → Director → CreativeIntent →
  Production → Candidate → Formal → Editing → FinalFilm）是**业务主流程**，
  不得被表达为用户可编辑的 Node Graph，也不得暴露 PromptNode / ImageNode /
  VideoNode / TTSNode / CompositeNode 这类节点给用户。
- Director 的控制流称 **Director Runtime Flow**，不叫 DirectorGraph。
- 明确禁止的概念：`DirectorGraph`、`CreativeGraph`、`SkillGraph`、
  `EditingGraph`、`UIWorkflowGraph`。

完整定义见 [PRODUCTION_GRAPH.md](PRODUCTION_GRAPH.md)。

---

## 六、依赖方向

模块依赖矩阵只在 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) 定义，本文不复制
第二份矩阵。产品主链、运行时调用顺序和源码 import 方向是不同关系，不相互推导。

Frontend UI 经统一 API Client 访问 Backend API；API 与 Worker 是不同的入站适配角色，
按用例调用 Application / Domain / Runtime。Application 是权限、事务和用例编排职责，
不要求新增同名包或空壳转发层，也不授予绕过依赖门的权限。
普通领域查询和管理操作无需经过 Director、Creative 和 Production 的完整生产路径。

两条不可让步的推论：

- Production 不允许通过 Director 才能访问 Creative Layer；
- Creative Layer 不允许知道具体 Runtime。

可执行判定规则与布局参考见 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md)，
当前违规调用链只由 [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) 记录。

---

## 七、完整系统只用六句话解释

> **Director 决定做什么。**
> **Creative Layer 把创意决定编译成 CreativeIntent。**
> **ProductionGraph 决定为了实现 CreativeIntent 需要执行哪些生产步骤。**
> **NodeRun 记录每一个生产步骤的执行事实。**
> **ProviderOperation 记录真实外部模型调用。**
> **Artifact 记录最终生产结果。**

创作语义进入媒体生产时的概念关系如下；这是业务关系摘要，不是每个请求必须执行的调用栈：

```text
User → Director → Creative Layer → CreativeIntent → ProductionGraph
     → NodeRun → ProviderOperation → Artifact → Candidate / Formal
     → Editing → FinalFilm
```

---

## 八、长期禁止项与变更边界

- 新建 Skill / Style / Editing Runtime；
- 引入 Temporal 或新的 Agent 框架；
- 把 ProductionGraph 暴露成用户节点编辑器，或模仿 ComfyUI；
- 为同一业务事实新造同义的 Workflow / Task / Job / Run、重复状态机或竞争性事实源。
- 把 MasterRun、DirectorTurn、BusinessFlow、ProductionGraph、NodeRun 等不同生命周期的事实强行合并为一个泛化 Run/Workflow；不同事实可以使用不同名称，但必须明确唯一含义和权威归属。

Runtime 重写、物理目录迁移和产品范围扩展不是日常清理的隐含任务；确有需要时，
由 Owner 依据具体方案决定。保留核心原则不禁止消除歧义或修正文档；改变原则、
放宽依赖或新增豁免必须显式决定，不能以“清理”或检查失败代替授权。
