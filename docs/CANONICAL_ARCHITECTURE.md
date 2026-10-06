# CANONICAL_ARCHITECTURE — DramaForge 架构宪法

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Date: 2026-09-22 / Alembic head: 20260922_0077

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

**当前实现事实以代码、迁移、测试和运行证据为准。** 本文件中任何尚未在代码中落地
的条目都会显式标注 `[未落地]`，不得被当作已完成能力引用。

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

任何新功能必须能挂到上面这条主链的某一步。挂不上去，说明它要么是这十三个概念
之一的实现细节，要么就是超范围设计。

---

## 二、只有两个 Runtime

DramaForge 只有两个真正拥有生命周期、Worker、队列和恢复语义的 Runtime。

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

Provider 只是被 Production Runtime 调用的外部执行能力，不拥有自己的 Worker、
队列、Checkpoint 或恢复语义。

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

**当前物理位置：** `backend/app/director/creative_capabilities/`。
它目前挂在 `director/` 目录下只是历史目录布局，**不代表 Creative 是 Director 的私有
能力**。逻辑边界以本文件为准；物理迁移属 Phase 2，本轮未执行。

Success 标准（Phase 2 验收）：Creative Layer 能在不启动 Director Runtime 的前提下
解析 Style、解析 Skill、编译 VisualBible、编译 ShotLanguage、生成/验证
CreativeIntent。

---

## 四、CreativeIntent 是唯一中间协议

前段（用户 + Director + LLM + Style + Skill + VisualBible + ShotLanguage +
Assets + Scene/Shot）与后段（ProductionGraph + Provider + TTS/FFmpeg）之间
**必须通过 CreativeIntent 连接**。

后续所有 Provider 都不直接消费 Skill 或 Style，而是消费：

```text
CreativeIntent + ModelCapability
```

再编译为 `EffectiveProviderRequest`。

### 4.1 当前实现状态（重要）

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

权威优先级门（代码已实现，不得改写）：

```text
explicit user value > accepted proposal > project override > pack default
```

### 4.2 与执行方案字段表的差异 `[未落地]`

执行方案建议 CreativeIntent 至少包含：

```text
subject / character / scene / camera / composition / lighting / motion
/ performance / continuity / references / style / audio / duration
/ quality_constraints
```

**当前代码没有这些顶层字段。** 现有实现把这些内容分散在：

- `visual_bible_patch`（lighting / contrast / texture / lens_language /
  composition / camera_behavior / motion_feel / production_design /
  post_processing / palette）；
- `shot_director_intent_patch`（shot_size / camera_angle / lens_intent /
  camera_motion / composition / focus_strategy / coverage / reaction_rule /
  cutting_rule / continuity）；
- `effective_values`（平铺后的有效值，含 `shot_size` / `camera_angle` /
  `camera_motion` / `continuity` 别名归一）；
- `ShotReferenceIntent`（references，见下）。

因此 **Phase 3 的真实任务不是"新建 CreativeIntent"，而是决定是否把
`CompiledCreativeIntent` 的嵌套结构收敛为执行方案建议的 canonical 顶层字段表**，
并明确哪些字段 canonical、哪些可选、哪些属 Provider-specific extension。

### 4.3 参考意图已在契约层定义

`ShotReferenceIntent` 定义在 `backend/app/contracts/shot_reference.py`，承担
"引用身份而非 prompt 兜底"的语义（"deliberately carries identity rather than
name/prompt fallback"），并由 `CreativeIntent` 侧编译进 ProductionCommand。

生产编译器旧导入路径仅重新导出同一类型。contracts → production 的反向依赖已移除，
与 [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md) §4.5、
[ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) §4 一致。

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

目标依赖方向：

```text
Frontend
   ↓
Application
   ↓
Director
   ↓
Creative
   ↓
CreativeIntent
   ↓
Application
   ↓
Production
   ↓
Provider
   ↓
Artifact
```

允许：

```text
director   → creative
director   → domain
production → creative.contracts
production → providers
production → domain
```

禁止：

```text
creative      → director
creative      → production
providers     → director
provider adapter → application service
```

两条不可让步的推论：

- Production 不允许通过 Director 才能访问 Creative Layer；
- Creative Layer 不允许知道具体 Runtime。

可执行判定规则、当前违规清单与目标物理布局见
[MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md)。

---

## 七、完整系统只用六句话解释

> **Director 决定做什么。**
> **Creative Layer 把创意决定编译成 CreativeIntent。**
> **ProductionGraph 决定为了实现 CreativeIntent 需要执行哪些生产步骤。**
> **NodeRun 记录每一个生产步骤的执行事实。**
> **ProviderOperation 记录真实外部模型调用。**
> **Artifact 记录最终生产结果。**

且所有产品行为都能回到唯一主链：

```text
User → Director → Creative Layer → CreativeIntent → ProductionGraph
     → NodeRun → ProviderOperation → Artifact → Candidate / Formal
     → Editing → FinalFilm
```

---

## 八、本轮明确不做

- 新建 Skill / Style / Editing Runtime；
- 引入 Temporal 或新的 Agent 框架；
- 把 ProductionGraph 暴露成用户节点编辑器，或模仿 ComfyUI；
- 重写 Director Runtime 或 Production Runtime；
- 为目录美观一次移动全部文件；
- 新造 Workflow / Task / Job / Run 同义概念；
- 扩大当前 V1 产品范围。
