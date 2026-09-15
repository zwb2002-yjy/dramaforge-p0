# DramaForge 综合设计与执行方案

**文档日期**: 2026-09-07  
**项目代号**: DramaForge  
**当前分支**: dev  
**基线 commit**: d024b2d

---

## 执行摘要

本方案基于 DramaForge 项目当前 dev 分支实际状态与外部 AI 短剧工作台规划文档，提供**面向专业个人创作者的 AI 影视制作工作台**的完整设计和执行路径。

### 核心定位

DramaForge 是**以场景和镜头为核心、以项目资产为稳定底座、以生产图谱（Production Graph）为执行内核**，允许用户与导演智能体共同操作，并能够把导演意图透明编译到不同 AI 模型上的专业 AI 影视制作工作台。

### 当前状态概览

- **执行依据**: Professional 七方案执行集（`docs/plans/professional-program-v2/`）
- **V1 Goal**: 统一创作主链（目前 IN PROGRESS，部分 Task 已 COMPLETE）
- **技术栈**: FastAPI + PostgreSQL + Redis + Arq + React + TanStack + Docker
- **核心能力**: Production Graph、Provider Plugin、Model Profile、Director Workflow、Canvas Revision

---

## 第一部分：架构现状与设计原则

### 1.1 当前架构总览

```
┌─────────────────────────────────────────────────┐
│  前端工作台 (React + TanStack Router/Query)      │
│  Canvas First UI + Director Board + Editing      │
└────────────────┬────────────────────────────────┘
                 │ REST API + SSE
┌────────────────┴────────────────────────────────┐
│  API Gateway (FastAPI)                           │
│  - 认证与授权 (JWT + RLS)                        │
│  - Workspace/Project 隔离                        │
│  - 事件流 (SSE via Outbox)                       │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────┴────────────────────────────────┐
│  核心业务层                                       │
│  ├─ Production Graph (生产图谱)                  │
│  ├─ Director Workflow (导演智能体)               │
│  ├─ Provider System (模型供应商插件化)           │
│  ├─ Asset Management (资产版本管理)              │
│  ├─ Canvas Revision (画布版本控制)               │
│  └─ Consistency Engine (一致性引擎)              │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────┴────────────────────────────────┐
│  执行层                                           │
│  ├─ Outbox Dispatcher (事件派发)                 │
│  ├─ Arq Workers (异步任务执行)                   │
│  │  ├─ Default Queue (轻量任务)                  │
│  │  └─ Heavy Queue (生成任务)                    │
│  └─ Provider Runtime (模型调用编译)              │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────┴────────────────────────────────┐
│  基础设施层                                       │
│  ├─ PostgreSQL 15 (主数据库 + RLS)               │
│  ├─ Redis 7 (队列 + 缓存)                        │
│  ├─ MinIO (对象存储)                             │
│  └─ LiteLLM Proxy (统一 LLM 网关，可选)          │
└─────────────────────────────────────────────────┘
```

### 1.2 核心设计原则

#### 原则 1: Production Graph 是系统核心

**Production Graph（生产图谱）**是整个系统的执行内核，不是 Agent。每个加工步骤是一个 Node，各自带独立的输入哈希与 checkpoint。

```
Shot 生产图示例:
  ├─[Node] Keyframe   (图像生成)
  │    ↓
  ├─[Node] Video      (图生视频，依赖 Keyframe)
  │    ↓
  ├─[Node] Voice      (TTS，可与 Video 并行)
  │    ↓
  ├─[Node] Subtitle   (字幕生成)
  │    ↓
  ├─[Node] Composite  (合成，依赖 Video+Voice+Subtitle)
  │    ↓
  └─[Node] Review     (质检)
```

**关键价值**：
- **增量重跑**: 改字幕只重跑 `Subtitle→Composite`，不触发 `Keyframe/Video` 重生成
- **局部恢复**: 单个 Node 失败只影响其下游，上游产物全部命中缓存
- **成本可控**: 重跑成本 = 变更节点及下游成本，非整个 Shot 重来

#### 原则 2: 用户才是导演

```
用户 = 导演
导演智能体 = 导演助手
画布 = 当前制作事实
模型 = 执行工具
```

导演智能体可以：
- 分析剧本、设计镜头、推荐参考
- 编译提示词、建议模型
- 帮助修改画布、帮用户执行

但：
- **导演智能体没有创作主权**
- 用户可以全部接受、部分接受、全部否定、完全关闭 AI 助手
- 系统必须接纳用户当前决定，不能"表面认同，后台仍按 AI 方案执行"

#### 原则 3: 模型能力透明化

通过 **Provider Plugin + Manifest + Production Profile** 体系：
- 每个模型的原生能力（参考图、ControlNet、运镜、角色绑定）被显式声明
- 用户看到的不是"统一削平的最低公分母"，而是当前模型的真实能力
- Provider Compiler 将导演意图编译为模型原生请求，不做黑盒改写

#### 原则 4: 双维度一致性

- **剧情连续性**（四层）：资产状态时间线 + 约束规则引擎 + 生成前注入 + 生成后质检
- **角色视觉一致性**（七层）：
  1. 角色参考图（最重要，解决 80%）
  2. Reference Set（多角度参考图库）
  3. Prompt 锁定（固定角色 Prompt）
  4. Seed 固定
  5. **Face Embedding 检测闭环**（最值得做，保证发现错误）
  6. Reference Injection（综合注入）
  7. Video 后校验（视频漂移检测）

#### 原则 5: 首版单用户专业工作台

- V1 允许一个人完成全流程
- 不在 V1 引入复杂的多人角色、审核链、团队审批体系
- 目标用户：AI 短剧制作人员、独立影视创作者、ComfyUI/可灵等平台的专业用户

---

## 第二部分：技术架构详细设计

### 2.1 数据模型核心

#### 组织层级
```
Workspace (工作空间)
  └─ Project (项目)
      └─ Episode (集/章节，可选)
          └─ Scene (场景)
              └─ Shot (镜头)
```

#### 资产体系
```
AssetLibrary
  ├─ Character (角色)
  │   ├─ reference_images (参考图集)
  │   ├─ canonical_reference (权威正脸图)
  │   ├─ reference_set (多角度: front/left/right/full_body)
  │   ├─ locked_prompt (固定角色 Prompt)
  │   ├─ anchor_seed (固定 Seed)
  │   └─ threshold_profile (自适应阈值)
  ├─ Location (场景/地点)
  ├─ Prop (道具)
  └─ VoiceProfile (声音配置)
```

#### 生产图谱
```sql
-- production_graphs 表
CREATE TABLE production_graphs (
    id UUID PRIMARY KEY,
    shot_id UUID NOT NULL REFERENCES shots(id),
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ
);

-- graph_nodes 表
CREATE TABLE graph_nodes (
    id UUID PRIMARY KEY,
    graph_id UUID NOT NULL REFERENCES production_graphs(id),
    node_type VARCHAR(50) NOT NULL,  -- keyframe/video/voice/subtitle/composite/review
    executor VARCHAR(100) NOT NULL,  -- agent:*/tool:*/model:*
    depends_on UUID[],               -- 上游节点 ID
    input_hash VARCHAR(64),          -- 输入指纹，决定缓存命中
    status VARCHAR(20),              -- pending/running/cached/completed/failed/stale
    artifact_id UUID REFERENCES artifacts(id),
    cost DECIMAL(8,4),
    checkpoint JSONB,
    created_at TIMESTAMPTZ
);
```

#### Canvas Revision（画布版本）
```sql
-- canvas_revisions 表：镜头级版本控制
CREATE TABLE canvas_revisions (
    id UUID PRIMARY KEY,
    shot_id UUID NOT NULL REFERENCES shots(id),
    revision_number INT NOT NULL,
    snapshot JSONB NOT NULL,         -- 完整镜头状态快照
    author_id UUID,
    commit_message TEXT,
    parent_revision_id UUID,
    created_at TIMESTAMPTZ
);
```

#### Director Workflow（导演智能体）
```sql
-- director_threads 表：对话线程
CREATE TABLE director_threads (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    scope VARCHAR(50),               -- project/scene/shot
    scope_entity_id UUID,
    status VARCHAR(20),
    created_at TIMESTAMPTZ
);

-- director_proposals 表：AI 建议方案
CREATE TABLE director_proposals (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES director_threads(id),
    proposal_type VARCHAR(50),       -- scene_design/shot_breakdown/model_suggestion
    content JSONB NOT NULL,
    user_action VARCHAR(20),         -- pending/accepted/rejected/modified
    applied_at TIMESTAMPTZ
);
```

### 2.2 Provider 插件化体系

#### 三层架构

```
┌──────────────────────────────────────┐
│  Catalog (不可变能力声明)             │
│  - 每个模型的原生能力 manifest         │
│  - 参考图/ControlNet/运镜支持情况      │
└──────────────┬───────────────────────┘
               │
┌──────────────┴───────────────────────┐
│  Binding (用户密钥与配置绑定)          │
│  - BYOK 密钥存储 (Fernet 加密)        │
│  - 每个 Workspace 独立 binding         │
│  - Pricing snapshot                   │
└──────────────┬───────────────────────┘
               │
┌──────────────┴───────────────────────┐
│  Compiler + Runtime (执行层)          │
│  - 将导演意图编译为模型原生请求        │
│  - EffectiveRequest 快照              │
│  - 幂等、恢复、重试                    │
└──────────────────────────────────────┘
```

#### 统一执行器接口

```python
class NodeExecutor(ABC):
    @abstractmethod
    async def run(self, node: GraphNode, inputs: dict) -> Artifact:
        """执行节点，返回产物"""
        pass

# 执行器注册表
EXECUTOR_REGISTRY = {
    "agent:generation": GenerationAgentExecutor(),
    "agent:director": DirectorAgentExecutor(),
    "tool:ffmpeg": FFmpegExecutor(),
    "tool:tts": TTSExecutor(),
    "model:flux": FluxImageExecutor(),
    "model:comfyui": ComfyUIExecutor(),
    "model:kling": KlingVideoExecutor(),
    # 扩展新能力 = 注册新执行器
}
```

### 2.3 一致性引擎详细设计

#### 剧情连续性（四层）

```
第一层：资产状态时间线
  └─ 记录角色服装、道具持有在各 Shot 的变化

第二层：约束规则引擎
  └─ 定义 ContinuityRule（类型、范围、enforcement、修复模板）

第三层：生成前注入
  └─ 查询上游 Shot 状态，构造约束 Prompt 片段注入

第四层：生成后质检
  └─ 调用视觉 LLM 分析产物，规则匹配检测冲突
```

**数据结构**：
```sql
-- asset_state_timeline 表
CREATE TABLE asset_state_timeline (
    id UUID PRIMARY KEY,
    asset_id UUID NOT NULL,
    asset_type VARCHAR(50),          -- character/prop/location
    shot_id UUID REFERENCES shots(id),
    state_snapshot JSONB NOT NULL,   -- {costume:"白西装", holding:["合同"]}
    state_changes JSONB,
    locked BOOLEAN DEFAULT FALSE,
    verified_by_user BOOLEAN DEFAULT FALSE
);

-- continuity_rules 表
CREATE TABLE continuity_rules (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    name VARCHAR(100),
    type VARCHAR(50),                -- character_appearance/prop_continuity
    scope VARCHAR(20),               -- project/episode/scene
    condition JSONB NOT NULL,
    enforcement VARCHAR(20),         -- block/warn/suggest
    violation_severity VARCHAR(20),  -- critical/high/medium/low
    repair_template TEXT
);
```

#### 角色视觉一致性（七层）

**核心原则**: 预防层（参考图/Prompt/Seed）负责"尽量对"，检测层（Face Embedding）负责"保证发现错"。

```
第一层：角色参考图 (80% 效果)
  └─ 每个角色一张权威参考图，生成时默认注入

第二层：Reference Set (多角度)
  └─ front/left/right/full_body，按景别自动选参考图

第三层：Prompt 锁定
  └─ Character.locked_prompt，任何镜头都拼接而非重写

第四层：Seed 固定
  └─ Character.anchor_seed，模型支持时使用

第五层：Face Embedding 检测闭环 ⭐ (最值得做)
  └─ InsightFace 提取特征 → 生成后比对 → 低于阈值自动重生成

第六层：Reference Injection
  └─ 综合注入：Canonical + Embedding + Prompt + Seed

第七层：Video 后校验
  └─ 视频每 5 帧抽样 → 比对 → 标记漂移片段
```

**关键实现**：
```python
class Character(Base):
    # ... 基础字段
    canonical_reference: str             # 权威正脸图
    reference_set: JSONB                 # {"front":url, "left":url, ...}
    locked_prompt: str                   # 固定角色 Prompt
    anchor_seed: int | None              # 固定 Seed
    threshold_profile: JSONB             # 自适应阈值 Profile

class ThresholdProfile:
    """每角色个性化基线，避免固定阈值误杀/漏检"""
    base: float                          # 均值 - k*标准差
    per_shot_type: dict[str, float]      # 侧脸用侧脸阈值
    sample_size: int
    confidence: str                      # low/high

async def verify_with_adaptive_threshold(generated, shot, character):
    profile = get_or_calibrate(character)
    threshold = profile.per_shot_type.get(shot.shot_type, profile.base)
    sim = FaceConsistencyCheck().verify(generated, character)
    return sim, sim >= threshold
```

**阈值自适应校准**（关键）：
- 用角色自己的参考图集算类内相似度分布
- 阈值 = 均值 - 2*标准差（低于此值说明比最差的合法参考图还差）
- 分景别细化：侧脸镜头用侧脸基线，不拿正脸标准卡侧脸
- 运行期反馈修正：用户手动通过/打回后调整阈值

---

## 第三部分：当前实施状态与 Gap 分析

### 3.1 已完成能力

根据 `dev@d024b2d` 和 V1 Goal 状态：

✅ **基础架构**
- PostgreSQL 数据库 + Alembic 迁移（52 个 migration）
- Redis + Arq 任务队列
- MinIO 对象存储集成
- JWT 认证 + RLS 行级安全
- Outbox + SSE 事件流

✅ **核心业务**
- Production Graph 骨架（`production_graphs` + `graph_nodes` 表）
- Provider Catalog + Binding + Compiler（完整插件化体系）
- Production Profile（多模型制作配置）
- Canvas Revision（画布版本控制）
- Asset References（资产引用管理）
- Director Workflow Core（导演线程、提案、自主执行）

✅ **V1 Goal 部分 Task**
- G0: 权威基线与架构登记 (COMPLETE)
- G1: Story Authoring Proposal Chain (COMPLETE)
- G2: CreativeTemplate 与 ProjectCreativeProfile (COMPLETE)
- G3: DirectorAutonomy (COMPLETE)
- G4: Proactive Director Recommendation (COMPLETE*)
- G5: Creation UX 与统一 Canvas (COMPLETE)
- G6: OpenCut Director 主动剪辑建议 (COMPLETE)

✅ **前端工作台**
- Canvas First UI
- Director Board 2D
- Model Profile Settings
- Asset Reference Picker
- Editing Workspace
- Experiment Compare

### 3.2 进行中任务

⏳ **V1 Goal 当前阻塞**（GOAL_BLOCKED）
- G7: 统一主链 E2E 与 current-HEAD 双路径真实 Provider Golden (IN PROGRESS)
- G8: Current-HEAD Release Candidate Gate (IN PROGRESS)

**阻塞原因**：
> 验收复核发现 Final Film Timeline 真渲染、Worker 异步链、重试语义、前端等待/dirty gate 与 current-HEAD 证据仍未闭环

### 3.3 核心 Gap（相对外部规划文档）

#### Gap 1: Face Embedding 检测闭环未实现

**外部规划**：第五层 Face Embedding 是护城河核心，InsightFace 提取特征 → 生成后比对 → 低于阈值自动重生成

**当前状态**：
- Migration `20260813_0025_remove_face_embedding_contract.py` **删除了** Face Embedding 相关字段
- Migration `20260819_0029_retire_face_review_nodes.py` **退役了** Face Review Nodes

**原因推测**：可能因"首版不集成人脸 embedding、生物特征识别或相似度阈值"决策（见 README.md）

**建议**：
- 如确认不做自动人脸一致性检测，明确告知用户"由人工试拍验收"
- 如未来需要，重新设计 Face Embedding 层作为可选增强

#### Gap 2: 剧情连续性引擎未完整实现

**外部规划**：四层架构（资产状态时间线 + 约束规则引擎 + 生成前注入 + 生成后质检）

**当前状态**：
- `asset_state_timeline` 表不存在（未在 migration 中找到）
- `continuity_rules` 表不存在
- `backend/app/consistency/continuity.py` 存在，但需检查完整度

**建议**：
- 补充 `asset_state_timeline` 和 `continuity_rules` 表
- 实现生成前约束注入机制
- 实现生成后质检 Agent

#### Gap 3: 交付与导出系统不完整

**外部规划**：
- P0: MP4 + SRT + 剪映草稿 + 素材包
- P1: DaVinci XML (FCPXML)
- P2: EDL / AAF

**当前状态**：
- `exports` 表存在
- `backend/app/delivery/` 模块存在
- 需确认剪映草稿、DaVinci XML 导出实现状态

#### Gap 4: 成本追踪与预算守卫

**外部规划**：
- 镜头级成本追踪（`cost_ledger` 表）
- 预算超限阻断生成（`BudgetGuard`）
- 区分首次生成与重生成成本

**当前状态**：
- 需确认成本追踪实现状态

---

## 第四部分：分阶段实施计划

### 4.1 实施策略

**策略原则**：
1. **不推倒重来**：保留底层执行内核（Production Graph / Provider / Worker），重构产品外壳
2. **闭环当前 V1 Goal**：优先完成 G7/G8，使 V1 主链达到可发布状态
3. **补齐护城河能力**：一致性引擎、成本控制、交付系统
4. **渐进式增强**：Face Embedding 作为可选增强，不阻塞 V1

### 4.2 Phase 1: V1 Goal 闭环（优先级最高）

**目标**：解除 GOAL_BLOCKED 状态，完成 G7/G8

**任务清单**：
- [ ] G7-E: Final Film Timeline 真渲染与 Worker 异步链闭环
- [ ] G7: 统一主链 E2E 证据收集
- [ ] G7-B: Current-HEAD Golden 双路径验证
- [ ] G8: Release Candidate Gate 自动化
- [ ] G8: Source/image/evidence 绑定验证

**交付标准**：
- V1 Goal 状态从 GOAL_BLOCKED → GOAL_DONE
- 可从根目录 Docker Compose 启动完整系统
- Template Start / Free Start 双路径可运行
- 真实 Provider（Agnes/MiniMax）生成证据收集
- 前端等待/dirty gate 与后端异步链对齐

**时间估算**：2-3 周

### 4.3 Phase 2: 一致性引擎补全

**目标**：实现剧情连续性四层架构

**任务清单**：
- [ ] 设计并创建 `asset_state_timeline` 表 migration
- [ ] 设计并创建 `continuity_rules` 表 migration
- [ ] 实现资产状态时间线追踪服务
- [ ] 实现约束规则引擎（DSL 解析、规则匹配）
- [ ] 实现生成前约束注入（Prompt 拼接）
- [ ] 实现生成后质检 Agent（视觉 LLM 调用）
- [ ] 前端：一致性报告 UI、修复建议交互
- [ ] 测试：服装突变、道具凭空出现等场景

**交付标准**：
- 能检测"角色服装突变"、"道具凭空出现"
- 质检报告能定位具体 Shot 和违反的规则
- 用户点击修复后自动调整 Prompt 并重新生成

**时间估算**：3-4 周

### 4.4 Phase 3: 成本控制与追踪

**目标**：镜头级成本追踪、预算守卫、重生成成本区分

**任务清单**：
- [ ] 确认或创建 `cost_ledger` 表
- [ ] 实现 `BudgetGuard` 预算检查中间件
- [ ] 在每个 NodeRun 完成后记录成本
- [ ] 区分 `is_rerun` 标记（一致性检测触发的重跑）
- [ ] 前端：项目成本仪表盘、预算预警 UI
- [ ] 测试：预算超限阻断、成本报告准确性

**交付标准**：
- 每个生成任务的成本记录到 `cost_ledger`
- 项目预算超限时阻止新生成
- 用户可查看镜头级成本明细
- 可区分首次生成与重生成成本

**时间估算**：2 周

### 4.5 Phase 4: 交付系统完善

**目标**：完整交付能力（MP4 + 剪映草稿 + DaVinci XML + 素材包）

**任务清单**：
- [ ] 确认现有 `exports` 表和 `delivery` 模块状态
- [ ] 实现 MP4 + SRT 导出（FFmpeg 合成）
- [ ] 实现剪映草稿导出（`.draft_content` JSON 生成）
- [ ] 实现 DaVinci XML (FCPXML) 导出
- [ ] 实现素材包导出（ZIP 打包，包含所有 Artifact + 元数据）
- [ ] 前端：导出格式选择、下载链接管理
- [ ] 测试：导出包可在剪映/DaVinci 中打开

**交付标准**：
- 用户点击"导出"后生成 MP4、SRT、剪映草稿、素材包
- 导出包可在剪映中打开并继续编辑
- DaVinci XML 可导入 DaVinci Resolve
- 素材包包含所有镜头原始文件和项目 JSON

**时间估算**：2-3 周

### 4.6 Phase 5: Face Embedding 可选增强（后续）

**目标**：作为可选功能提供角色视觉一致性自动检测

**前置条件**：
- 产品决策：是否重新引入人脸相似度自动检测
- 技术验证：InsightFace 集成、阈值校准可行性

**任务清单**（如决定做）：
- [ ] 恢复 `Character.face_embedding` 字段
- [ ] 集成 InsightFace 库
- [ ] 实现特征提取服务
- [ ] 实现自适应阈值校准（`threshold_profile`）
- [ ] 实现生成后自动比对
- [ ] 实现低于阈值自动重生成
- [ ] 实现视频后校验（抽帧比对）
- [ ] 前端：Face Embedding 开关、阈值配置 UI

**交付标准**：
- 用户可选择开启/关闭 Face Embedding 检测
- 开启后，生成的角色人脸相似度低于阈值自动重生成
- 视频帧漂移可被检测并标记

**时间估算**：4-5 周（含技术验证）

---

## 第五部分：技术风险与缓解措施

### 5.1 技术风险矩阵

| 风险类型 | 影响程度 | 发生概率 | 缓解措施 |
|---------|---------|---------|---------|
| V1 Goal 异步链闭环复杂 | 高 | 中 | 增加 Worker 日志、Outbox 事件追踪、前端轮询降级 |
| 模型 API 不稳定 | 高 | 中 | 多 Provider 备份、失败重试、降级策略 |
| 一致性检测误判 | 中 | 中 | 自适应阈值、人工复核、规则可调 |
| 导出格式兼容性 | 中 | 中 | 剪映草稿逆向维护、FCPXML 规范验证 |
| Face Embedding 阈值校准困难 | 中 | 高 | 充分技术验证后再决定是否做，不阻塞 V1 |
| 成本追踪不准确 | 低 | 低 | Provider Pricing Snapshot、事务级成本记录 |

### 5.2 关键依赖

**外部依赖**：
- Agnes API（图像生成）
- MiniMax API（视频生成）
- Azure TTS / 火山 TTS（语音合成）
- InsightFace（如启用 Face Embedding）
- FFmpeg（媒体处理）

**缓解措施**：
- 多 Provider 备选（可灵、即梦、ComfyUI 本地）
- 本地 ComfyUI 作为离线 fallback
- Provider Catalog 系统允许快速添加新模型

---

## 第六部分：质量门禁与验收标准

### 6.1 代码质量门禁

**已有门禁**（`scripts/run_quality_in_docker.ps1`）：
- 后端静态检查（Ruff / MyPy）
- 后端单元测试
- PostgreSQL 迁移验证
- API 合同测试
- 前端 lint / typecheck / unit / build / E2E
- Canonical surface scan（阻止已删除功能重现）

**补充门禁**：
- [ ] Production Graph 增量重跑测试
- [ ] Provider Compiler 编译正确性测试
- [ ] 一致性引擎规则匹配测试
- [ ] 成本追踪准确性测试

### 6.2 V1 MVP 验收标准

**功能完整性**：
- ✅ 从剧本到分镜的完整流程可运行
- ✅ Template Start / Free Start 双路径工作
- ✅ 导演智能体可提供建议，用户可接受/拒绝
- ✅ Canvas First UI 可操作
- ⏳ 一致性检查能识别服装/道具冲突（Phase 2）
- ⏳ 成本追踪到镜头级（Phase 3）
- ⏳ 导出 MP4 + 剪映草稿（Phase 4）
- ⏳ 增量重跑：改字幕不触发图像视频重跑（验证现有实现）

**技术指标**：
- API P95 响应时间 < 500ms（读操作）
- Worker 任务成功率 > 95%
- 数据库查询 P95 < 100ms
- 前端首屏加载 < 3s

**安全合规**：
- JWT 认证 + RLS 行级安全
- BYOK 密钥 Fernet 加密存储
- 日志脱敏（API 密钥不入日志）
- 单用户模式默认启用

### 6.3 Release Gate

参考 `docs/runbooks/release-gate-board.md`：
- [ ] 自动化质量门禁全部通过
- [ ] 真实 Provider 生成证据（Agnes/MiniMax）
- [ ] 用户流程端到端可运行
- [ ] 离线安装包测试通过
- [ ] 证据报告绑定 commit SHA、dirty 状态、环境

---

## 第七部分：成本估算与资源规划

### 7.1 开发人力成本

**Phase 1-4 总估算**：11-13 周

| 角色 | 人数 | 周薪（参考） | 总周数 | 成本 |
|-----|------|------------|--------|------|
| 全栈/后端负责人 | 1 | ￥8000 | 13 周 | ￥104000 |
| 前端工程师 | 1 | ￥6000 | 13 周 | ￥78000 |
| AI/Agent 工程师 | 0.5 | ￥7000 | 13 周 | ￥45500 |
| **人力总成本** | | | | **￥227500** |

**Phase 5（Face Embedding，可选）**：+4-5 周
- 额外成本：约 ￥95000

### 7.2 基础设施成本

**开发/测试环境**（月成本）：
- 云服务器 4 核 8G × 2：￥600
- PostgreSQL 4 核 16G：￥800
- Redis 8GB：￥200
- 对象存储 500GB：￥150
- **月度小计**：￥1750

**模型 API 测试额度**：
- 文本模型（剧本拆解、分镜生成）：￥2000
- 图像模型（首帧生成）：￥3000
- 视频模型（图生视频）：￥5000
- **测试总计**：￥10000

**Phase 1-4 总成本预算**：
- 人力：￥227500
- 基础设施（3 个月）：￥5250
- 模型测试：￥10000
- 其他（域名/证书/工具）：￥2000
- **总计**：约 ￥245000

### 7.3 单集制作成本估算（参考）

**场景**：30 个镜头、每镜头 4 秒

| 环节 | 调用次数 | 单次成本 | 小计 |
|-----|---------|---------|------|
| 剧本拆解 | 1 | ￥1.5 | ￥1.5 |
| 资产生成 | 5 | ￥0.8 | ￥4 |
| 分镜生成 | 1 | ￥2 | ￥2 |
| 首帧生成 | 60 | ￥0.2 | ￥12 |
| 视频生成 | 30 | ￥2 | ￥60 |
| 配音 TTS | 30 | ￥0.1 | ￥3 |
| 一致性质检 | 30 | ￥0.5 | ￥15 |
| **首次生成小计** | | | **￥97.5** |
| 重生成（30% 图像） | 18 | ￥0.2 | ￥3.6 |
| 重生成（20% 视频） | 6 | ￥2 | ￥12 |
| **单集总计** | | | **约￥113** |

**成本优化**：
- 草稿阶段使用便宜模型
- 本地 ComfyUI 降低首帧成本
- Production Graph 增量重跑避免无谓重生成

---

## 第八部分：开发协作与 Git 工作流

### 8.1 分支策略

```
main (受保护)
  ├─ 只保留经过验证的稳定版本
  └─ 只能通过 dev → main 的 PR 更新

dev (日常开发)
  ├─ 本地 dev 分支进行 Task 开发
  ├─ Task 验证通过后提交
  └─ 除非 Owner 明确要求，不推送到 origin/dev

agent/<task-id> (短期分支，可选)
  ├─ 并行隔离或紧急修复时使用
  ├─ 从本地 dev 创建（紧急修复从 main）
  ├─ 配合 .worktrees/<task-id> 使用
  └─ PR 先合回 dev（紧急修复合回 main 后也要同步回 dev）
```

### 8.2 Commit 规范

```
<type>(<scope>): <subject>

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

**Type**:
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档变更
- `test`: 测试相关
- `refactor`: 重构（不改变外部行为）
- `perf`: 性能优化
- `chore`: 构建/工具变更

**Scope**: `navigation`, `director`, `production`, `provider`, `frontend`, `backend`

### 8.3 PR 流程

1. 在本地 `dev` 或 `agent/<task-id>` 分支完成开发
2. 运行质量门禁：`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1`
3. 创建 PR：`gh pr create --base dev --title "feat(scope): description"`
4. PR 描述末尾添加：`🤖 Generated with [Claude Code](https://claude.com/claude-code)`
5. 等待 Owner (@zwb2002-yjy) 批准和合并
6. Agent 不得批准、合并或记录 `MERGED`

### 8.4 Task 记录

使用 `.agent-control/control.ps1` 记录 Task 生命周期：

```powershell
# 任务开始
.\.agent-control\control.ps1 -Operation log -Message "START Task G7-E: Final Film async chain"

# 任务完成
.\.agent-control\control.ps1 -Operation log -Message "COMPLETE Task G7-E: evidence at tmp/g7e-evidence/"

# 任务失败
.\.agent-control\control.ps1 -Operation log -Message "FAIL Task G7-E: Worker retry logic not converging"

# 任务暂停
.\.agent-control\control.ps1 -Operation log -Message "PAUSE Task G7-E: blocked on Provider API quota"
```

---

## 第九部分：下一步行动计划

### 9.1 立即行动（本周）

1. **确认 V1 Goal 阻塞点**
   - 阅读 G7/G8 Task Contract 详细内容
   - 运行当前 dev 分支，复现阻塞问题
   - 与 Owner 确认优先级和解除阻塞路径

2. **环境验证**
   ```powershell
   # 启动完整栈
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
   
   # 健康检查
   curl http://localhost:8080/gateway-health
   curl http://localhost:8080/health
   
   # 运行质量门禁
   .\scripts\run_quality_in_docker.ps1
   ```

3. **Current Evidence 收集**
   - 记录当前 Final Film Timeline 渲染状态
   - 记录当前 Worker 异步链行为
   - 记录当前前端等待机制

### 9.2 Phase 1 任务分解（2-3 周）

**Week 1**:
- [ ] 分析 G7-E Task Contract 和现有代码
- [ ] 修复 Final Film Timeline 真渲染问题
- [ ] 增强 Worker 异步链日志和追踪
- [ ] 前端：实现 dirty gate 检查

**Week 2**:
- [ ] 修复前端等待机制与后端对齐
- [ ] 完成 G7-E 证据收集
- [ ] 开始 G7-B Current-HEAD Golden 验证
- [ ] 真实 Provider 端到端测试

**Week 3**:
- [ ] 完成 G7 所有 subtask
- [ ] 开始 G8 Release Gate 自动化
- [ ] Source/image/evidence 绑定实现
- [ ] V1 Goal 状态更新为 GOAL_DONE

### 9.3 长期路线图（6 个月）

**Q1 2027**:
- Phase 1-2 完成（V1 Goal 闭环 + 一致性引擎）
- V1.0 Release Candidate

**Q2 2027**:
- Phase 3-4 完成（成本控制 + 交付系统）
- V1.0 正式发布

**Q3 2027**:
- Phase 5 评估（Face Embedding 可选增强）
- 用户反馈迭代

**Q4 2027**:
- V2 规划（多用户协作、高级剪辑功能）

---

## 附录 A：关键技术决策记录

### A.1 为什么选择 Production Graph 而非传统 Agent 编排？

**问题**：AI 影视生产需要局部重跑能力（改字幕不重生成视频）

**方案对比**：
- ❌ 传统 Agent 编排：整个流程重来，成本高
- ❌ 简单状态机：难以表达复杂依赖关系
- ✅ **Production Graph (DAG)**：每个加工步骤是可缓存、可局部重跑的 Node

**优势**：
- 增量重跑：只重跑变更节点及下游，上游命中缓存
- 成本可控：重跑成本 = 变更路径成本
- 断点续传：单个 Node 失败不影响整个 Shot
- 可扩展：加新能力 = 注册新 Node 类型

### A.2 为什么 Provider 要插件化？

**问题**：不同 AI 模型原生能力差异大，统一削平会丢失高级功能

**方案对比**：
- ❌ 统一抽象层：削成最低公分母，浪费模型能力
- ❌ 硬编码每个模型：不可扩展，维护困难
- ✅ **Catalog + Binding + Compiler**：显式声明 + 透明编译

**优势**：
- 模型能力透明：用户看到真实能力，不是黑盒
- 快速集成新模型：注册 Catalog 即可
- BYOK 友好：用户自带密钥，Workspace 隔离

### A.3 为什么用户才是导演？

**问题**：AI 容易"自作主张"，导演意图被改写

**产品哲学**：
- ❌ AI 主导：系统给完整方案，用户只能全盘接受
- ❌ AI 黑盒：表面认同用户，后台仍按 AI 方案执行
- ✅ **用户主导 + AI 辅助**：AI 可以很主动，但没有创作主权

**实现**：
- Director Proposal 是建议，不是命令
- Canvas 是当前制作事实，用户可随时修改
- 系统必须接纳用户决定，不能偷偷改回去

---

## 附录 B：外部文档对照表

| 外部规划章节 | 当前实现状态 | Gap | 优先级 |
|------------|------------|-----|--------|
| 1.3 技术栈选型 | ✅ 完全一致（FastAPI + PostgreSQL + Redis + React） | 无 | - |
| 3.2 四层剧情连续性架构 | ⚠️ 部分实现 | 缺 `asset_state_timeline` 和 `continuity_rules` 表 | P1 |
| 3.7 七层角色视觉一致性 | ❌ Face Embedding 已删除 | 第五层检测闭环未实现 | P2（可选） |
| 3.8 Production Graph | ✅ 已实现 | 需验证增量重跑 | P0 |
| 4.1 六类 Agent 职责 | ✅ Director Agent 已实现 | 其他 Agent 按需补充 | P1 |
| 5.1 单集成本估算 | ⚠️ 部分实现 | 缺 `cost_ledger` 表和预算守卫 | P1 |
| 附录 A API 设计 | ✅ 已实现 | 需补充导出 API | P1 |
| 附录 B 数据库 Schema | ✅ 大部分已有 | 缺一致性相关表 | P1 |
| 附录 C Docker Compose | ✅ 已实现 | 生产环境配置需加固 | P2 |

---

## 附录 C：术语表

| 术语 | 定义 |
|-----|------|
| **Production Graph** | 生产图谱，将每个加工步骤建模为 DAG 节点，支持增量重跑 |
| **Node** | 生产图谱中的一个加工步骤（如 Keyframe、Video、Voice） |
| **Executor** | 节点执行器（Agent、Tool、Model） |
| **Canvas** | 画布，当前制作事实的可视化表示 |
| **Canvas Revision** | 画布版本，支持回滚和分支实验 |
| **Director Agent** | 导演智能体，AI 辅助创作的核心 Agent |
| **Proposal** | AI 提案，导演智能体给出的建议方案 |
| **Provider** | 模型供应商（如 Agnes、MiniMax、可灵） |
| **Catalog** | 不可变能力声明，每个模型的原生能力 manifest |
| **Binding** | 用户密钥与配置绑定，Workspace 级隔离 |
| **Compiler** | 编译器，将导演意图编译为模型原生请求 |
| **EffectiveRequest** | 实际请求快照，记录编译后发给模型的完整请求 |
| **Artifact** | 生产产物（图像、视频、音频等） |
| **RLS** | Row-Level Security，PostgreSQL 行级安全策略 |
| **BYOK** | Bring Your Own Key，用户自带密钥 |
| **Outbox** | 事件发件箱模式，确保事件可靠派发 |
| **Arq** | Python 异步任务队列库 |

---

## 总结

本方案整合了 DramaForge 项目当前实际状态与外部 AI 短剧工作台完整规划，提供了一份**可执行的分阶段实施路线图**。

**核心要点**：

1. **保留执行内核**：Production Graph、Provider Plugin、Worker 异步执行是系统基石，不推倒重来

2. **闭环 V1 Goal**：优先解除 GOAL_BLOCKED 状态，完成 G7/G8 任务，使主链达到可发布状态

3. **补齐护城河**：分阶段补全一致性引擎（剧情连续性）、成本控制、交付系统

4. **Face Embedding 可选**：作为后续增强，不阻塞 V1 发布

5. **用户是导演**：产品哲学贯穿全栈，AI 辅助但无创作主权

**预期成果**：

- **Phase 1 完成后**：V1 主链可端到端运行，Release Candidate 就绪
- **Phase 2-4 完成后**：完整专业工作台，具备一致性检测、成本控制、多格式交付能力
- **Phase 5（可选）**：自动人脸一致性检测，进一步降低试错成本

**总投入估算**：Phase 1-4 约 ￥245000（3 个月），Phase 5 额外约 ￥95000（如决定做）

---

**文档维护**：本方案基于 2026-09-07 项目状态编制，应随项目进展持续更新。
