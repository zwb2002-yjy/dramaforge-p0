# PRODUCTION_GRAPH — Graph / Node / NodeRun 定义权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）
Date: 2026-09-15 / Base: dev 5ea45d6 / Alembic head: 20260910_0066

本文件只回答一件事：**ProductionGraph 怎么组织执行计划。**

运行机制（怎么跑：Outbox → Worker → ProviderOperation → Artifact）见
[PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md)；世界观见
[CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md)；术语见
[DOMAIN_VOCABULARY.md](DOMAIN_VOCABULARY.md)。

---

## 一、ProductionGraph 是什么

> ProductionGraph 表示：为完成一次生产任务，需要执行哪些生产步骤，以及这些步骤
> 之间的依赖关系。

- 它是 **Production Runtime 内部的执行计划**，不是产品交互模型。
- 领域文档中的 `Graph` **默认只指 ProductionGraph**。
- **产品主流程不是 Node Graph。** Project → Story → Scene → Shot → Director →
  CreativeIntent → Production → Candidate → Formal → Editing → FinalFilm 是业务
  主流程，**不得**表达为用户可编辑的节点图。
- 用户**不需要**面对 `PromptNode` / `ImageNode` / `VideoNode` / `TTSNode` /
  `CompositeNode`。一旦暴露，产品就退化成 ComfyUI 类型的工作流工具。

**明确禁止的其他 Graph 概念：** `DirectorGraph`、`CreativeGraph`、`SkillGraph`、
`EditingGraph`、`UIWorkflowGraph`。

Director 的控制流叫 **Director Runtime Flow**，见
[DIRECTOR_RUNTIME.md](DIRECTOR_RUNTIME.md)。

---

## 二、四个概念的固定区别

| 概念 | 一句话 | 代码锚点 |
|---|---|---|
| **Node** | ProductionGraph 内一个有明确输入输出的**生产步骤定义**。不是普通函数 | `execution/models.py::GraphNode`（`node_key` / `node_type` / `cacheable`） |
| **NodeRun** | 某个 Node 的**一次实际执行事实**（排队 → 运行 → 终态） | `execution/models.py::NodeRun` |
| **ProviderOperation** | 一次**真实外部模型/API 调用**事实 | `execution/models.py::ProviderOperation` |
| **Artifact** | 生产出来的**不可变结果**及血缘 | `execution/models.py::Artifact`、`artifact_lineage.py` |

固定关系：

```text
ProductionGraph
      ↓
GraphVersion（可版本化，definition_hash）
      ↓
GraphNode
      ↓
NodeRun          1..N
      ↓
ProviderOperation   0..N
      ↓
Artifact
```

### 2.1 Node vs NodeRun

```text
VideoGenerationNode        ← 定义（一种）
    Shot 03 第一次生成 → NodeRun #1001
    用户重做          → NodeRun #1026
```

同一种 Node，不同的运行事实。持久化上由
`UniqueConstraint(graph_node_id, attempt_no)` 保证。

### 2.2 NodeRun vs ProviderOperation

```text
NodeRun: GenerateVideo
  ├── ProviderOperation #1 失败
  └── ProviderOperation #2 成功
```

- NodeRun 表示 **DramaForge 的业务执行步骤**。
- ProviderOperation 表示 **真实外部调用事实**。
- **只有 NodeRun 一个 owner**（`ProviderOperation.node_run_id`）。

### 2.3 Candidate / Formal 不属于 Graph Node

它们是**生产结果的业务状态和用户选择**：

```text
Artifact A / Artifact B / Artifact C   ← 都是 Candidate
        用户选择 B  →  B 成为 Formal
```

实现事实：**没有 Candidate 表**。候选直接从 NodeRun + Artifact 派生；正式选择记录在
`Shot.formal_keyframe_artifact_id` / `Shot.formal_video_artifact_id`。

Video 执行默认使用正式关键帧，且在不存在正式关键帧时**必须 fail closed**，绝不退化为
"用最新一张图"（`production/formal_selection.py::require_formal_keyframe`）。

---

## 三、Graph definition 的真实形态

Graph 的 `definition` 是一个 JSON 文档（`GraphVersion.definition`），由
`graph_factory` 构造：

```json
{
  "template_key": "...",
  "template_version": "1.0.0",
  "nodes": [{"key": "keyframe", "type": "keyframe", "display_name": "Shot keyframe"}],
  "edges": [["prompt", "keyframe"]],
  "cacheable": true
}
```

`definition` 有 `definition_hash`；`GraphVersion` 有草稿/已发布状态，发布需显式
`publish`。节点结构变化会被 `materialize_definition` 与 `create_graph` 校验
（`production/service.py`）。

### 3.1 三个 Graph 定义来源（当前事实）

| 来源 | template_key | 是否被真实生产执行 |
|---|---|---|
| `execution/shot_pipeline.py::shot_pipeline_definition` | `shot-p0-v1` | **是**——Workbench execution 与 Experiment 的规范 Shot 图 |
| `production/templates.py::dialogue_post_dub_definition` | `dialogue-post-dub-shot-v1` | 仅作为 Workflow 模板目录内容（见下） |
| `production/final_film.py` 的内部图 | `final-film-v1` | **是**——成片尾部渲染 |
| `director/workflows/template_nodes.py`（5 个） | `single-character-monologue-v1`、`two-character-dialogue-v1`、`action-motion-shot-v1`、`establishing-reaction-insert-v1`、`montage-sequence-v1` | **否**——仅供 `workflow_planning` / `workflow_overview` 规划与只读展示 |

**关键事实：`director/workflows/` 不是第二套 Graph 世界观。**
`WorkflowTemplateRegistry` 里的 `graph_factory` 正是 ProductionGraph 的
`definition` 构造器（`director/workflows/contracts.py` 注释即声明
"always returns a ProductionGraph ``definition`` dict"）。它是**模板目录 + 只读导航**，
不是并行执行引擎：真实的 Shot 生产固定使用 `shot-p0-v1`。

因此这是**发现性问题（模板目录分散在三个模块）**，不是**概念性问题（两套 Graph）**。
详见 [ARCHITECTURE_MAPPING.md](ARCHITECTURE_MAPPING.md) 问题 5。

---

## 四、Node 类型（持久化事实）

`node_runs` / `graph_nodes` 的 `node_type` 是数据库枚举，当前仅十个值：

| node_type | 业务含义 | 类别 |
|---|---|---|
| `prompt_compose` | 把创作意图与 prompt 契约编译为该镜头可执行的 prompt 文档 | 纯上游（零成本本地） |
| `keyframe` | 生成关键帧图像 | 真实生产 / Provider |
| `identity_review` | 角色一致性证据与判定 | 零成本本地 review |
| `video` | 由正式关键帧生成视频 | 真实生产 / Provider |
| `video_review` | 视频漂移证据与判定（node_key 常为 `video_drift_review`） | 零成本本地 review |
| `voice` | 对白语音合成 | 本地 `local-voice-v1` |
| `subtitle` | 字幕生成 | 零成本本地 |
| `composite` | 合成该镜头成片片段 | 零成本本地 |
| `continuity_review` | 连续性证据与判定 | 零成本本地 review |
| `export` | 导出 | 交付 |

新增 `node_type` 需要数据库迁移，并需通过下一节的准入规则。

---

## 五、Node 准入规则

为防止 ProductionGraph 再度膨胀，**禁止把普通函数包装成 Node**。

一个步骤只有满足以下多项条件时，才允许成为 Production Node：

- 有独立失败可能；
- 值得独立重试；
- 存在显著计算或 Provider 成本；
- 有独立产物；
- 存在异步等待；
- 需要被血缘追踪；
- 后续步骤会明确依赖其结果。

**适合作为 Node：**

```text
Keyframe Generation
Video Generation
TTS
Subtitle Generation
Identity Review
Continuity Review
Composite
Final Render
```

**不适合作为 Node（保持普通函数）：**

```text
load config
format prompt
convert enum
read style
validate simple field
```

### 5.1 对现有 Node 的判定

| 判定 | Node | 理由 |
|---|---|---|
| **KEEP** | `keyframe`、`video`、`voice`、`subtitle`、`composite`、`export` | 独立失败、独立重试、独立产物、真实成本或异步等待 |
| **KEEP** | `identity_review`、`video_review`、`continuity_review` | 独立产物（证据 Artifact）、条件分支的判定依据、可独立重试 |
| **BORDERLINE** | `prompt_compose` | 无 Provider 成本、无异步等待，但**有独立产物**（prompt 文档 Artifact）且被下游 `keyframe` 显式依赖，并被标记为纯上游节点（`_PURE_UPSTREAM_NODE_TYPES`）。当前保留 |
| **已降级为函数** | `prompt`（作为独立 node_type 不存在） | 只在 `PURE_NODES` 判定集合中出现，无独立持久化类型 |
| **DELETE** | 无 | 当前无纯 enum 转换 / 字符串拼接型 Node |

**结论：当前 10 个 node_type 未出现"普通函数被包装成 Node"的滥用。**
唯一的边界项是 `prompt_compose`，理由如上。

---

## 六、ProductionGraph 的真正价值

ProductionGraph 不是为了"节点化"，而是为了三件事。

### 6.1 并行执行

```text
                ┌→ TTS ─────────┐
Video Generate ─┤                ├→ Composite
                └→ Subtitle ────┘
```

`shot-p0-v1` 已表达该形状：`video → composite`、`voice → composite`、
`subtitle → composite` 三条并行入边。

### 6.2 条件执行

```text
Keyframe
   ↓
Identity Review
   ├── PASS → Video
   └── FAIL → Repair Keyframe
```

Review 节点产出证据 Artifact，作为分支判定依据。

### 6.3 最小重算

当前**已落地**的机制：

1. **NodeRun 身份与幂等**
   - `UniqueConstraint(project_id, idempotency_key)`：同一意图重复提交不会二次执行。
   - `input_hash`：输入变化即视为不同运行。
   - `UniqueConstraint(graph_node_id, attempt_no)` + `parent_run_id`：重做产生新
     NodeRun，血缘保留。
2. **Content-addressed Artifact 去重**
   - `UniqueConstraint(project_id, content_hash, artifact_type)`。
   - `get_or_create_artifact()` 命中相同内容时复用既有 Artifact，并把当前 NodeRun
     标记为 `cached`、写入 `reused_from_run_id`。
   - 默认**禁止跨 Shot 复用字节**：非 document 类型跨 NodeRun 复用会抛
     `ARTIFACT_NOT_INDEPENDENT`，除非显式 `allow_cross_run_reuse`（当前仅 audio 开启）。
     这防止一个 Shot 的媒体被另一个 Shot 静默认领。
3. **阶段化执行计划**
   - `WorkbenchExecutionPlan` 冻结 `stage`（`image_keyframe` / `video`）、模型槽位、
     引用编译与节点契约（`_STAGE_CONTRACT`）。
   - 因此"只改镜头运动"只需重建 `video` 阶段并显式复用既有正式关键帧，无需重新生成
     角色与关键帧。
4. **显式修复而非静默重跑**
   - Modification 通过 `assets/models.py::ShotChangeProposal.reusable_artifact_ids`
     声明可复用产物。
   - Repair 只能通过 `production/repair_service.py` 的显式计划回到 Production。

**尚未成形：** 一个独立的 **Production Planner**，即"由 CreativeIntent + 现有 Artifact
+ Formal 状态 + ModelCapability + 修改范围自动推导出**最小** ProductionGraph"的角色。
当前最小重算由调用方（Workbench 阶段选择 / 修复计划 / 可复用产物声明）驱动，而不是由
规划器自动推导。这是 Phase 4 的收敛目标。

---

## 七、明确不做

- 把 ProductionGraph 暴露成用户可见的节点编辑器；
- 模仿 ComfyUI；
- 为每个普通函数创建 Node；
- 引入第二套 Graph 世界观（`DirectorGraph` / `CreativeGraph` / `SkillGraph` /
  `EditingGraph` / `UIWorkflowGraph`）；
- 引入 `GenerationTask` / `RenderTask` / `WorkflowTask` / `MediaJob` 等同义概念。
