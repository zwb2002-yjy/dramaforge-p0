# DramaForge 架构决策与技术选型书

**编制日期**: 2026-07-13
**最近修订**: 2026-07-20（同步阶段切片、模块口径、人工媒体与运维边界）
**状态**: 架构方向已批准；`01_项目总需求.md` 至 `06_受控混合Agent运行时规范.md` 已构成按主题受控的 P0 实现冻结包。S0-A、S0-B 与关键 ADR 是接入真实 Provider、启用条件性交付和完成 P0 验收的实施 Gate。

> **文档优先级**：本书保存决策理由、取舍和路线；实现发生冲突时，以根目录 `01`–`06` 冻结包对应主题为准。`DramaForge双模式产品与架构汇报方案.md` 是决策摘要，`AI短剧工作台完整实施规划.md` 是归档历史，不再定义现行范围。

---

## 零、一级产品约束：双模式创作体验 `[新增 2026-07-13｜作为后续实现的总需求]`

DramaForge 必须在同一生产底座上提供两种可切换的创作体验：**快速出片模式**与**专业工作台模式**。

这是一项产品范围、领域模型和前端架构共同遵守的一级约束，不是汇报包装，也不是后续可选的皮肤功能。

### 0.1 产品结论：一个生产底座，两种工作入口

| 模式 | 面向用户 | 用户目标 | 主交互 | 系统承诺 |
|---|---|---|---|---|
| **快速出片模式** | 普通创作者、轻量运营人员 | 从创意、文本或剧本尽快得到可审核成片 | 对话式 Agent + 向导卡片 + 阶段确认 | 隐藏复杂配置，但不牺牲可追溯、可恢复和成本可控 |
| **专业工作台模式** | 需要精细控制的个人创作者 | 精细管理资产、剧本、分镜、任务、成本和交付 | 项目化工作台 + 可视化编辑 + 任务队列 | 暴露完整控制能力，支持审核与专业交付 |

两种模式不是两套产品，也不得分别维护项目、资产、任务、费用或导出记录。它们只是同一项目状态的不同操作界面。

### 0.2 共同真相与不可变约束

以下对象是两种模式共同读写的唯一业务真相：

```text
User / Workspace / Project
  ├─ Story Bible / Script / Episode / Scene / Shot
  ├─ Asset Library / Reference Set
  ├─ Production Graph / GraphVersion / NodeRun
  ├─ ProviderOperation / Artifact / Review
  ├─ Cost Ledger / Budget
  └─ Delivery Package / Audit Event
```

- 快速模式创建的内容必须直接落入正式 `Project`、资产、分镜和 Production Graph，不得保存为另一套“聊天草稿”或临时项目。
- 专业模式对同一项目做出的修改，必须立即成为快速模式后续 Agent 规划与生成时的上下文。
- Production Graph 是执行、重试、缓存、取消、成本和产物的唯一真相；对话记录不能替代图定义或任务状态。
- 工作模式是用户界面偏好与当前入口，不是项目类型、权限角色或数据隔离维度。切换模式不迁移数据、不复制项目、不丢失执行历史。
- 工作区私有隔离、RLS、预算、BYOK、审核与审计在两种模式下规则完全一致。快速模式的“简单”不能成为越权或绕过预算的路径。P0 不提供成员、邀请或团队协作。

### 0.3 快速出片模式：从意图到成片的受控 Agent 流程

快速模式应以“少输入、少决策、可确认”为原则。它可以采用类似 Agent 应用的对话入口，但不能只是开放式 Chat。

用户通过一句创意、完整文本或已有剧本启动项目。Agent 将意图整理成结构化 `Creative Brief`，再逐步生成可确认的剧本理解、角色与场景建议、分镜计划、风格方案和生成任务。

```text
输入创意 / 粘贴剧本 / 选择模板
        ↓
Agent 澄清并生成 Creative Brief
        ↓  用户确认
剧情与视觉方案 / 时长 / 风格 / 预算
        ↓  用户确认
分镜计划与首帧方案
        ↓  受预算保护地执行
生成、质检、自动修复、合成
        ↓
审核成片 → 下载或“进入专业工作台”精修
```

快速模式的最低功能要求：

1. 支持从创意、文本和剧本模板创建项目，并展示结构化理解结果。
2. 将关键决策做成可编辑的确认卡片，而不是把关键配置隐藏在长对话中。
3. 在调用付费 Provider、批量生成、自动重生成或超出预算前，展示预估消耗并要求确认。
4. 显示生成进度、失败原因、成本、可用产物与下一步建议；状态来自 Graph 快照和事件流。
5. 任一阶段均可“进入专业工作台”，直接查看并编辑当前项目、资产、分镜、Graph、任务和产物。
6. Agent 的工具调用只可通过稳定的领域 Interface 创建计划或请求执行；不得直接修改节点状态或绕过 Production Graph。

### 0.4 专业工作台模式：从可控生产到个人交付

专业模式面向需要精修和专业交付的个人创作者。它不应重复实现一套生成能力，而是将快速模式已经创建的正式对象完整呈现并开放细粒度控制。

| 工作区 | 核心能力 |
|---|---|
| 项目概览 | 剧集、进度、预算、风险、待审核项与交付状态 |
| 剧本与知识 | Story Bible、角色关系、剧情事件、连续性约束 |
| 资产库 | 角色、场景、道具、声音、参考图与锁定版本 |
| 分镜与生产图 | Shot 编辑、镜头排序、节点依赖、局部重跑与缓存命中 |
| 任务与质检 | 队列、失败重试、取消、相似度、漂移与人工审核 |
| 成本与模型 | Provider、BYOK、预算、实际费用和降级记录 |
| 交付 | MP4、SRT、素材包、时间线 JSON 及后续专业格式 |

专业模式中的 Agent 是辅助入口。它可以帮助拆分剧本、生成分镜、定位问题或批量提出修改，但所有结果必须以可审阅的项目变更呈现。

### 0.5 双模式转换合同

| 转换 | 必须行为 | 禁止行为 |
|---|---|---|
| 快速 → 专业 | 打开同一个项目与当前 GraphVersion；保留对话上下文、计划、运行历史、成本和产物 | 新建副本项目、重新排队已完成任务、丢失确认记录 |
| 专业 → 快速 | 读取专业模式的最新已保存项目快照；以摘要方式提示当前阶段和待处理事项 | 覆盖人工锁定资产、分镜或审核结论 |
| 工作区私有隔离 | 仅当前所有者可在两个模式中执行动作；变更进入审计事件与实时同步 | 因模式不同而绕过 RLS、预算或审核，或以项目角色模拟 P0 协作 |

“快速模式”与“专业模式”的关系类似同一 Agent 产品中的 Chat 与 Agent 工作流：前者帮助用户表达意图并推进任务，后者提供过程透明度与可控性。但 DramaForge 的差异是，二者都必须落到可审计的影视生产图中。

### 0.6 为双模式设置的深 Module

新增 **创作体验 Module（Creation Experience Module）**。它的 Interface 负责把用户意图转为正式项目计划，并在两种模式之间提供同一项目快照。

```text
start_project(intent, template_id?) -> ProjectSnapshot
refine_brief(project_id, instruction) -> PlanPreview
confirm_plan(project_id, plan_id) -> ProjectSnapshot
request_generation(project_id, scope, budget_confirmed) -> RunSummary
open_workbench(project_id) -> ProjectSnapshot
resume_quick_flow(project_id) -> GuidedStep
```

该 Module 的实现可以使用 LLM、提示词模板、会话记忆、表单卡片和前端路由，但调用方只依赖上述 Interface。

这样可以把 Agent 编排、确认门槛、模式转换、上下文摘要和错误恢复收敛在一个深 Module 内，避免这些规则分散在 Chat 页面、工作台页面和 Worker 中。

### 0.7 验收标准与阶段调整

双模式需求在 P0 即纳入架构和数据模型，并在以下阶段分步交付：

| 阶段 | 双模式交付物 | 验收 Gate |
|---|---|---|
| **S1** | 双模式应用壳、统一项目路由、创作体验 Module Interface、模式偏好 | 同一项目可在两个入口打开；权限与数据范围一致 |
| **S2** | 快速出片最小闭环：文本 → 计划确认 → 一张首帧 → 相似度/成本 → 进入工作台 | 不靠人工搬运数据即可从快速模式切到工作台查看同一 Run |
| **S3** | 快速模式的预算确认、失败解释、重试建议与恢复；专业模式读取完整 Graph 快照 | 取消、失败、缓存、预算状态在两种模式显示一致 |
| **S4** | 专业工作台完整业务闭环；双向上下文同步；个人审核工作流 | 手工锁定资产或分镜后，快速模式不会擅自覆盖 |
| **S5** | 两种模式共享交付中心、回归测试和可观测性看板 | 同一项目从任一入口发起都能得到可复现交付包 |

所有双模式场景必须纳入端到端测试：模式切换无数据副本、成本只记一次、同一 NodeRun 不重复执行、人工锁定不被 Agent 覆盖、权限与对象 URL 不因模式而扩大。

---
## 一、总体架构

### 1.1 五层架构（维持原规划）

```
用户界面层（快速出片模式 + 专业工作台模式；React 18 + Vite）
       │ REST + SSE
项目与资产层（Project / Script / Shot / Asset + 一致性约束）
       │
Agent编排与任务层 (Production Graph + 状态机)
       │
生成执行层 (模型适配器 + Arq Worker + FFmpeg)
       │
交付与生态层（MP4 + SRT + 素材包 + 时间线 JSON；剪映草稿经 S0-B 后条件启用）
```

### 1.2 核心认知：Production Graph 是系统真正的核心

`Project → Episode → Scene → Shot` 只是数据组织层级。

每个 Shot 内部的生产步骤（Keyframe → Video → Voice → Subtitle → Composite → Review → Export）是独立的 DAG 节点。每个节点带 `input_hash`（输入指纹），决定是否命中缓存。

**这决定了**：
- 改字幕 → 只重跑 Subtitle → Composite → Export，Keyframe/Video/Voice 零成本
- 换视频 → 只重跑 Video → Composite → Export
- 所有 Agent、FFmpeg、TTS、ComfyUI 调用都是图里的一个 Node

### 1.3 产品概念视图（不是代码模块）

```
DramaForge
├── Creation Experience  快速模式的意图、确认、模式切换与项目快照
├── Project              项目/剧集/场次/镜头（数据层级）
├── Asset Library        角色/场景/道具/声音
├── Story Bible          世界观/风格/剧情设定
├── Production Graph     ★ 生产 DAG，编排与恢复的核心
├── Consistency Engine   剧情连续性(四层) + 角色视觉一致性(七层)
├── Model Router         多 Provider 路由 / BYOK / 成本路由
├── Render Pipeline      节点执行器：LLM / 图像 / 视频 / TTS / FFmpeg / ComfyUI
└── Delivery             MP4 / SRT / 素材包 / 时间线 JSON / 条件性剪映草稿
```

这些名称用于解释产品，不授权建立同名服务或平行目录。P0 不单独建设 Knowledge Graph、事件图谱或人物关系图产品能力；世界观与风格首先落在 `projects.style_bible` 和受控资产中，剧情连续性落在 `consistency` 的状态时间线、规则、Review 与 Violation 中。

### 1.4 产品概念到 `03` 代码模块的唯一映射

| 产品概念 | P0 代码归属 | 边界 |
|---|---|---|
| User / Workspace / Project / BYOK | `access` | 私有工作区、Project 本体、所有权校验、RLS 和工作区加密 Provider 凭据。 |
| Creation Experience | `creation` | Brief/Plan、AgentRun、确认、物化与 ProjectSnapshot。 |
| Script / Episode / Scene / Shot / Asset / Character / Reference / Artifact | `assets` | 内容层级、资产、参考和 Artifact 生命周期。 |
| Story Bible | `access` 中的 `Project.style_bible` + `assets` | 不建立独立 bible 服务。 |
| Production Graph | `production` | GraphVersion、Node/Edge、NodeRun、hash、缓存和局部重跑。 |
| Model Router / Provider 执行 | `providers` + `execution` | Adapter 协议、ProviderOperation、预算、成本、取消与回调。 |
| Render Pipeline / Worker | `execution` + `workers` + `providers` | 不拥有 Graph 或领域状态机。 |
| Consistency Engine | `consistency` | 角色与剧情规则、Review、Violation 和人工决策。 |
| Event / Outbox / SSE | `events` | 事件分发，不作为业务真相源。 |
| 可靠任务派发 | `production.scheduler` / `runtime.scheduler` | 只消费已提交 Outbox，不拥有 AgentRun/NodeRun 状态机。 |
| Delivery | `delivery` | Export、SRT、timeline JSON、FFmpeg 合成和交付包。 |

代码目录和依赖方向只以 `03_全局目录规范.md` 为准。若某个产品概念无法落入以上模块，先提出 ADR，不得新建 `project`、`knowledge_graph`、`model_router` 或 `render_pipeline` 平行模块。

---

## 二、技术选型（定稿）

### 2.1 后端

| 层次 | 选型 | 版本 | 理由 |
|------|------|------|------|
| **语言** | Python | 3.12+ | 异步生态成熟，AI 库最全 |
| **Web 框架** | FastAPI | 0.115+ | 原生 async，Pydantic v2 集成，自动 OpenAPI |
| **数据校验** | Pydantic | v2 | FastAPI 内置，v2 比 v1 快 5-50 倍 |
| **ORM** | SQLAlchemy 2.0 async | 2.0+ | 原生 async，与 FastAPI 同源 |
| **异步数据库驱动** | asyncpg | 0.30+ | PostgreSQL 异步驱动，比 psycopg2 快 2-3 倍 |
| **数据库迁移** | Alembic | 1.14+ | SQLAlchemy 官方迁移工具 |
| **任务队列** | **Arq** | 0.26+ | 原生 async/await，与全异步栈一体（见决策1修订，事实性纠错） |
| **实时推送** | SSE + Redis Streams | — | 浏览器原生支持；关键事件走 Streams 可回放，断线重连不丢（见决策4修订） |
| **对象存储** | MinIO | latest | S3 兼容，私有化部署 |
| **媒体处理** | FFmpeg | 6+ | 命令行封装，视频拼接/抽帧/合成 |
| **图像处理** | Pillow | 11+ | 缩略图、格式转换 |
| **人脸识别** | InsightFace (ONNX Runtime) | 0.7+ | CPU 可运行，无需 CUDA，512 维特征向量 |
| **配置管理** | pydantic-settings | 2+ | 与 FastAPI/Pydantic 同源 |
| **依赖注入** | FastAPI Depends | 内置 | 不需要额外 DI 框架 |
| **密钥加密** | cryptography (Fernet) | 43+ | AES-256 对称加密用户 API Key |
| **HTTP 客户端** | httpx | 0.28+ | 异步，用于外部 API 调用 |

### 2.2 前端

| 层次 | 选型 | 版本 | 理由 |
|------|------|------|------|
| **框架** | React + TypeScript | 18 + 5.x | 组件化，类型安全 |
| **构建** | Vite | 6+ | 快速 HMR |
| **路由** | TanStack Router | 1.x | 类型安全 URL，参数自动推导 |
| **服务端状态** | TanStack Query | 5.x | 缓存、重取、乐观更新 |
| **客户端状态** | Zustand | 5.x | 轻量，无 boilerplate |
| **表单** | React Hook Form + Zod | 7.x + 3.x | 复杂表单校验 |
| **UI 组件** | Radix UI + Tailwind CSS | latest + 3.4/4.x | 无障碍，可定制（shadcn 对 v3/v4 均兼容） |
| **组件封装** | shadcn/ui | latest | Radix 上层开箱即用封装 |
| **SSE 客户端** | 原生 EventSource | — | 浏览器内置，无需额外依赖 |

### 2.3 基础设施

| 层次 | 选型 | 版本 |
|------|------|------|
| **数据库** | PostgreSQL | 15+ |
| **缓存/队列** | Redis | 7+ |
| **容器化** | Docker Compose | v2 |
| **反向代理(生产)** | Nginx | 1.26+ |
| **监控** | Prometheus + Grafana | latest |
| **本地推理(可选)** | ComfyUI | latest (GPU profile) |

---

## 三、关键架构决策

### 决策 1：Arq 替代 Python RQ

原规划写的是 Python RQ。**改为 Arq**，理由：

- 整个后端是 async 的（FastAPI + SQLAlchemy 2.0 async + asyncpg），RQ 是同步的，Worker 里需要 `asyncio.run()` 或写两套代码
- Arq 原生 async/await，与全异步栈一体——这是选它的**唯一核心理由**

> **[修订 2026-07-13｜事实性纠错]** 原文另两条论据有误，已删除：①Arq 的维护者是 **Samuel Colvin（Pydantic 作者）**，不是 FastAPI 作者（tiangolo）；②Arq **默认同样用 pickle** 序列化，要 JSON 需自行配置 `job_serializer`，并不比 RQ 天然安全。因此"选 Arq"的正当依据只有"async 原生"这一条。
>
> **代价须知**：Arq 生态较薄，没有 Flower / rq-dashboard 级现成监控。长视频任务的可观测性需自建 job 状态表 + 轻量看板（复用第八节的 `event_log`）。

### 决策 2：Arq 多队列隔离算力与 I/O

生成任务分为两类，不能混跑：

| 队列 | 类型 | 函数示例 | 部署节点 |
|------|------|---------|---------|
| `default` | I/O 密集型 | 调用 OpenAI/Kling API、轮询状态、文本处理 | 普通 CPU 节点 |
| `heavy` | 算力密集型 | FFmpeg 合成、InsightFace Embedding、视频抽帧 | GPU/高配 CPU 节点 |

启动方式：
```bash
# I/O Worker
arq app.workers.main.WorkerSettings

# 算力 Worker
arq app.workers.main.HeavyWorkerSettings --queue heavy
```

### 决策 3：ctx 注入 async_sessionmaker，禁用共享 Session

Arq Worker 中多个 Job 并行执行，共享单一 `AsyncSession` 会导致 `PendingRollbackError`。

**规则**：ctx 注入 `async_sessionmaker`，每个 Worker 函数内部独立开 Session。

```python
# Worker 启动
async def startup(ctx):
    engine = create_async_engine(settings.database_url)
    ctx["sessionmaker"] = async_sessionmaker(engine, expire_on_commit=False)

# 每个 Job 函数
async def my_job(ctx, ...):
    async with ctx["sessionmaker"]() as session:
        ...
        await session.commit()
```

`expire_on_commit=False` 确保 commit 后对象不会标记为过期，避免后续访问触发隐式 lazy load。

### 决策 4：Production Graph 状态同步（DB 先写，再广播）

`GraphNode` 状态变更后需要让前端 SSE 立即感知。规则：

1. **先写 PostgreSQL**（落库）
2. **再发 Redis Pub/Sub**（广播给 SSE）
3. 绝不反过来

```python
async def _persist(self, node: GraphNode):
    async with self.sessionmaker() as session:
        session.add(node)
        await session.commit()  # ← 先确保落库
    
    # 落库成功后才广播，避免前端收到 "completed" 但 API 查不到
    # 落库成功后才广播，避免前端收到 "completed" 但 API 查不到
    await self.redis.publish(
        f"project:{project_id}:events",
        json.dumps({"event": "node.status_changed", "payload": {...}})
    )
```

> **[修订 2026-07-13｜补丢消息缺陷]** Redis **Pub/Sub 是 fire-and-forget**：SSE 断线重连期间广播的事件会永久丢失。两条修正：
> 1. 关键事件（`node.completed` / `node.failed` / `export.ready`）改走 **Redis Streams**，可回放，重连后从 last-id 补齐；
> 2. **SSE 重连必须触发一次全量 refetch**（前端 `queryClient.invalidateQueries`）——广播只当"提醒"，DB 才是唯一真相（与决策4的落库优先一致）。
>
> 高频进度百分比（`node.progress`）这类可丢事件可继续走 Pub/Sub，降低 Streams 写入压力。

### 决策 5：InsightFace 仅在 Arq heavy Worker 中调用

**严禁在 FastAPI 主进程中同步调用 InsightFace**。推理任务会阻塞事件循环。

| 阶段 | 部署方式 |
|------|---------|
| **MVP** | InsightFace 仅在 Arq heavy Worker 进程内调用（FastAPI 主进程永不导入相关模块） |
| **商业化** | 如并发量大，拆为独立 FastAPI + ONNX Runtime 微服务（无状态，水平扩展简单） |

> **[修订 2026-07-13｜补硬伤]** 只"放进 heavy Worker"**不够**：Arq Worker 本身是 async 事件循环，而 `insightface.get()` 是**同步 CPU 阻塞**调用，直接调用会卡死该 Worker 的事件循环、饿死同队列其他 Job。必须：
> - `loop.run_in_executor(None, ...)` 把推理丢**线程池**（ONNXRuntime 推理时释放 GIL，线程池即有效，无需进程池）；
> - 模型在 Worker `startup` 时**加载一次**，禁止每个 Job 重新 `prepare()`。
>
> 完整实现见第八节「实现2」。

### 决策 6：前端状态严格分层

```
TanStack Query（服务端状态）    →  所有 GET/POST/PUT 数据
Zustand（客户端状态）           →  仅 UI 状态（侧栏展开、当前选中项）
```

**不在 Zustand 存任何可用 TanStack Query 从服务端拿到的数据。**

### 决策 7：导出格式优先级

| 优先级 | 格式 | 当前承诺 |
|--------|------|------|
| **P0** | MP4 + SRT + 素材包 + 时间线 JSON | 保底交付；必须有黄金夹具和来源 Artifact/Run/成本回链。 |
| **条件性 P0** | 剪映草稿 (`.draft_content`) | 仅 S0-B 兼容性 Spike 通过、目标版本登记且开关启用后提供；否则降为 P0.5，不阻塞主闭环。 |
| **P1** | DaVinci XML (FCPXML) | 未来公开交换格式候选，不注册 P0 路由。 |
| **P2** | EDL (CMX3600)、AAF (SMPTE) | 未来专业交换格式候选，不注册 P0 路由。 |
| **不做** | PR 工程 (`.prproj`) | 私有二进制格式，无公开规范。 |

### 决策 8：LoRA 不是地基，是最后一层可选增强

角色视觉一致性靠七层架构。LoRA 仅在以下情况追加：
- 前六层反复报警的超高频主角
- 极致风格统一的品牌级项目

### 决策 9：BYOK 下的降级链只能在"用户已配置 key 的集合"内选

> **[修订 2026-07-13｜补 BYOK 悖论]** 原 S3 任务写了"主 Provider 失败 → 备用 → 本地 ComfyUI"，但 BYOK 意味着用户只带了自己有的 key，**盲目 fallback 到用户没配 key 的 Provider 会直接失败**。规则修正为：

- 降级候选池 = `用户已配置 key 的 Provider` ∩ `具备该能力（图像/视频/文本）的 Provider`
- 池内按「成本 / 质量评分」排序依次尝试
- 池空或全部失败 → fallback 到**本地 ComfyUI**（无需 key）→ 仍失败则该 Node 置 `failed`，进人工队列
- 每次降级决策写入 `event_log`，成本归因到**实际调用**的 Provider（非原计划 Provider）

---

## 四、项目结构（定稿）

```
dramaforge/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── workstation/       # WorkstationLayout, LeftPanel, CenterPanel, RightPanel
│   │   │   ├── storyboard/        # ShotTimeline, ShotCard, ShotEditor
│   │   │   ├── generation/        # TaskQueue, ProgressBar, GenerationPanel
│   │   │   ├── review/            # ConsistencyReport, ViolationCard
│   │   │   └── export/            # ExportPanel, DownloadManager
│   │   ├── hooks/
│   │   │   ├── useSSE.ts          # SSE 事件订阅
│   │   │   ├── useProject.ts      # TanStack Query hooks
│   │   │   └── useGeneration.ts
│   │   ├── lib/
│   │   │   ├── api.ts             # HTTP 客户端封装
│   │   │   └── types.ts           # 从后端 OpenAPI 自动生成
│   │   ├── stores/                # Zustand stores（仅 UI 状态）
│   │   └── pages/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── tailwind.config.ts
│
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app 工厂
│   │   ├── config.py              # pydantic-settings 配置
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── projects.py
│   │   │   │   ├── assets.py
│   │   │   │   ├── shots.py
│   │   │   │   ├── generation.py
│   │   │   │   ├── exports.py
│   │   │   │   └── events.py      # SSE 事件流
│   │   │   └── deps.py            # get_db, get_current_user
│   │   ├── models/                # SQLAlchemy ORM
│   │   │   ├── base.py
│   │   │   ├── project.py
│   │   │   ├── character.py
│   │   │   ├── shot.py
│   │   │   ├── generation_job.py
│   │   │   ├── artifact.py
│   │   │   ├── graph.py           # production_graphs + graph_nodes
│   │   │   ├── review.py
│   │   │   └── export.py
│   │   ├── schemas/               # Pydantic 请求/响应
│   │   ├── services/              # 业务逻辑层
│   │   │   ├── project_service.py
│   │   │   ├── generation_service.py
│   │   │   ├── consistency_service.py
│   │   │   └── export_service.py
│   │   ├── engine/                # ★ 一致性引擎（护城河）
│   │   │   ├── continuity/        # 剧情连续性（四层）
│   │   │   │   ├── state_timeline.py
│   │   │   │   ├── rule_engine.py
│   │   │   │   ├── pre_injection.py
│   │   │   │   └── post_qa.py
│   │   │   └── face/              # 角色视觉一致性（七层）
│   │   │       ├── embedding.py   # InsightFace ONNX 封装
│   │   │       ├── calibrator.py  # 阈值自适应校准
│   │   │       ├── reference_manager.py
│   │   │       └── video_drift.py # 视频逐帧校验
│   │   ├── adapters/              # 模型适配器
│   │   │   ├── base.py            # TextModel/ImageModel/VideoModel 抽象
│   │   │   ├── anthropic.py
│   │   │   ├── openai.py
│   │   │   ├── kling.py
│   │   │   ├── flux.py
│   │   │   └── comfyui.py
│   │   ├── graph/                 # ★ Production Graph（真正核心）
│   │   │   ├── templates.py       # Shot 生产图静态定义
│   │   │   ├── node.py            # GraphNode 模型
│   │   │   ├── executor.py        # NodeExecutor 注册表
│   │   │   ├── runner.py          # 拓扑排序 + 增量重跑
│   │   │   └── cache.py           # input_hash 缓存管理
│   │   ├── workers/               # Arq Worker
│   │   │   ├── main.py            # WorkerSettings / HeavyWorkerSettings
│   │   │   └── handlers/
│   │   │       ├── generation.py  # 图像/视频生成
│   │   │       ├── media.py       # FFmpeg 合成/抽帧
│   │   │       ├── face.py        # InsightFace 特征提取/批量校验
│   │   │       └── text.py        # LLM 调用
│   │   └── utils/
│   │       ├── storage.py         # MinIO 客户端
│   │       ├── ffmpeg.py          # FFmpeg 命令行封装
│   │       └── crypto.py          # Fernet 密钥加密
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── tests/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── Dockerfile.worker
│
├── docker-compose.yml             # PostgreSQL + Redis + MinIO + API + Worker
├── docker-compose.gpu.yml         # ComfyUI + Heavy Worker (GPU profile)
└── docs/
    └── architecture.md
```

---

## 五、开发策略

### 5.1 核心原则：仓库启动后优先证伪高风险假设

BOOT-0 先建立可运行仓库、质量门禁和本地基础设施，但不一次铺满全部业务表、页面和 Provider。骨架通过后优先验证技术不确定性最高的模块，再按 S1–S5 竖切补齐业务行为。

理由：
- 一致性引擎是人脸相似度阈值是否有效，在第1周就能知道，不用等到第8周
- 项目、资产和执行能力按当前 Gate 分期实现；进入某阶段的数据表必须逐字段符合 `04`，未进入的能力不注册假路由或假数据
- 如果 InsightFace 检测闭环跑不通，整个产品护城河不成立，需要换方向

### 5.2 开发计划：以双 Spike 和双模式垂直切片推进

本书不再维护与第十节并行的第二份排期。P0 的唯一阶段口径如下；详细实施 Gate 与验收项以 **10.9**、**10.12** 以及根目录冻结包为准。

| 阶段 | 周期 | 核心任务 | 验收 Gate |
|---|---:|---|---|
| **BOOT-0** | 按 Gate | 可运行仓库骨架、本地基础设施与质量门禁 | Compose 配置、API/Worker/前端壳、静态检查、测试、构建和目录检查通过。 |
| **S0-A** | 3 天 | 视觉一致性 Spike | 同/异角色和异常样本的 FAR、FRR、耗时、成本可复现。 |
| **S0-B** | 2 天 | 剪映兼容性 Spike | 干净环境可稳定导入最小草稿；失败即降为 P0.5。 |
| **S1** | 2 周 | 可信基础骨架 + 双模式应用壳 | RLS、Outbox、Graph 模型、Creation Experience Interface、统一项目路由通过。 |
| **S2** | 2 周 | 快速模式首帧垂直切片 | 文本→确认→首帧→相似度/成本→同项目工作台切换；不得视为 P0 完成。 |
| **S3** | 2.5 周 | Production Runtime 加厚 | 缓存、取消、重试、预算、恢复的幂等测试通过。 |
| **S4** | 3 周 | 专业工作台与完整生产闭环 | 10 Shot 完成 `shot-p0-v1` 全节点、审核和局部返工；人工锁定不被 Agent 覆盖。 |
| **S5** | 2.5 周 | 交付与集成硬化 | 10 Shot 流程无阻断，部署、恢复、安全回归和正式交付均可复现。 |

### 5.3 阶段任务的维护规则

- S0 的可复现实验报告写入 `docs/spikes/`；通过与否必须明确记录样本、版本、成本和结论。
- S1–S5 的可执行任务、数据迁移、测试和验收记录随根目录冻结包维护；本书只保留架构决策和 Gate 说明。
- 任何改变双模式共享事实、Provider 接入、交付承诺、阶段 Gate 或运行时合同的修改，必须先完成 ADR，再同步更新受影响的冻结文件与本书摘要。
## 六、开发环境启动清单

### 6.1 一次性初始化

```bash
# 1. 克隆仓库
git clone <repo-url> dramaforge && cd dramaforge

# 2. 启动基础设施（数据库、缓存、存储）
docker compose up -d postgres redis minio

# 3. 初始化后端
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head

# 4. 初始化前端
cd ../frontend
npm install

# 5. 启动全部服务
docker compose up -d
```

### 6.2 日常开发

```bash
# 终端 1：后端 API（热重载）
cd backend && uvicorn app.main:app --reload

# 终端 2：I/O Worker
cd backend && arq app.workers.main.WorkerSettings

# 终端 3：算力 Worker（需要 GPU/高配 CPU 时启动）
cd backend && arq app.workers.main.HeavyWorkerSettings --queue heavy

# 终端 4：前端（HMR）
cd frontend && npm run dev
```

### 6.3 需要 GPU 时

```bash
# 启动 ComfyUI + Heavy Worker（GPU 节点）
docker compose -f docker-compose.gpu.yml up -d
```

---

## 七、核心 models.py 速览

以下模型按定义顺序列出依赖关系，实现时以此为骨架：

```
User
  └─ UserKey (provider, encrypted_key)
  └─ Project (name, stage, style_bible, budget_limit)
       └─ Episode (episode_number, synopsis)
            └─ Scene (scene_number, location, time_of_day)
                 └─ Shot (shot_number, shot_type, camera_move, visual_description)
                      └─ ProductionGraph
                           └─ GraphNode (node_type, executor, depends_on, input_hash, status)
                      └─ GenerationJob (job_type, provider, model, status, cost, checkpoint)
                           └─ Artifact (artifact_type, storage_path, file_hash, face_similarity)
                                └─ Review (review_type, passed, violations)
       └─ Character (reference_set, face_embedding, locked_prompt, anchor_seed, threshold_profile)
       └─ AssetStateTimeline (asset_id, state_snapshot, state_changes)
       └─ ContinuityRule (type, condition, enforcement, violation_severity)
       └─ Export (format, status, download_url)
       └─ CostLedger (provider, model, cost, is_rerun)
       └─ EventLog (actor, action, target_type, target_id, payload, cost)   ← 业务审计（第八节新增）
```

---

## 八、关键实现补充（2026-07-13 修订新增）

> 本节补齐评审指出的三处硬伤实现与两处缺失（业务审计、认证/隔离），并给出一致性引擎的回归测试策略。

### 实现 1：`input_hash` —— Production Graph 的心脏

Production Graph 的增量重跑全部押在 `input_hash` 上，原文档未定义算法。两个致命边界：hash 少算（如漏掉模型版本）→ 换模型却命中旧缓存、静默出错；hash 多算（如把 `created_at`/`retry_count` 也算入）→ 永不命中、卖点归零。

**语义澄清**：生成是**非确定性**的，缓存是"输入未变则跳过重新生成"，而非"按内容记忆化"。任一生成节点重跑必产出新 `file_hash`，其下游因上游哈希变化被判 stale 而级联重跑——这是正确行为（换了首帧，视频就该重生成）。

```python
# graph/cache.py
import hashlib, json
from app.models.graph import GraphNode
from app.models.artifact import Artifact

# 白名单：只有这些参数变化才应使缓存失效（其余是噪声）
HASH_RELEVANT_PARAMS = {
    "keyframe": ["prompt", "seed", "model", "model_version",
                 "character_ref_hashes", "shot_type", "aspect_ratio"],
    "video":    ["prompt", "model", "model_version", "duration", "fps"],
    "voice":    ["text", "voice_id", "model", "speed"],
    "subtitle": ["text", "font", "style"],
    "composite":["ffmpeg_filter", "resolution"],
}

def compute_input_hash(node: GraphNode, upstream: list[Artifact], params: dict) -> str:
    """决定节点是否命中缓存；语义 = 输入未变则跳过重新生成。"""
    keys = HASH_RELEVANT_PARAMS.get(node.node_type, [])
    material = {
        "node_type": node.node_type,
        "executor":  node.executor,
        # ★ 上游用产物内容哈希，不用 artifact_id（同一 id 内容可能被替换）
        "upstream":  sorted(a.file_hash for a in upstream),
        # ★ 只纳入白名单参数，排除 created_at / retry_count 等噪声
        "params":    {k: params.get(k) for k in keys},
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()
```

```python
# graph/runner.py —— 增量重跑
async def rerun_from(self, graph, changed_node_id):
    dirty = graph.descendants(changed_node_id) | {changed_node_id}
    for node in graph.topological_order():
        new_hash = compute_input_hash(node, self._upstream(node), node.params)
        if node.id in dirty or new_hash != node.input_hash:
            node.status, node.input_hash = "stale", new_hash

    for node in graph.topological_order():
        if node.status != "stale":
            node.status = "cached"                       # 零成本，复用旧 artifact
            continue
        inputs = self._gather_upstream_artifacts(node)
        artifact = await EXECUTOR_REGISTRY[node.executor].run(node, inputs)
        # 生成非确定性：新 file_hash → 下游 upstream 哈希变 → 下游自动 stale → 级联
        node.artifact_id, node.status = artifact.id, "completed"
```

效果：改字幕 → 只有 subtitle 的 params 变 → 它 stale，keyframe/video 的 `input_hash` 未变 → cached 跳过。

### 实现 2：InsightFace 不阻塞 async Worker

```python
# workers/handlers/face.py
import asyncio
from functools import partial

async def startup(ctx):                       # Worker 启动时加载一次，别每 Job 重载
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1)
    ctx["face_app"] = app

def _sync_embed(app, image_bytes: bytes):
    import numpy as np, cv2
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    faces = app.get(img)
    if not faces:
        raise NoFaceDetected()
    return faces[0].normed_embedding          # 512 维，已归一化，cosine = 点积

async def extract_embedding(ctx, image_bytes: bytes) -> list[float]:
    loop = asyncio.get_running_loop()
    # ★ 同步 CPU 阻塞丢线程池；ONNXRuntime 推理释放 GIL → 线程池有效，无需进程池
    emb = await loop.run_in_executor(None, partial(_sync_embed, ctx["face_app"], image_bytes))
    return emb.tolist()
```

### 实现 3：`event_log` 业务审计表（ArcReel 强调、原文档缺失）

规则：**每个 `NodeExecutor.run` 前后各写一条**——既是审计，也是 Production Graph 的执行追踪与成本归因来源。

```sql
CREATE TABLE event_log (
    id          BIGSERIAL PRIMARY KEY,
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    actor       VARCHAR(50) NOT NULL,   -- 'user:<id>' | 'agent:generation' | 'system'
    action      VARCHAR(80) NOT NULL,   -- 'node.run' | 'shot.approve' | 'export.create'...
    target_type VARCHAR(40),            -- 'shot' | 'node' | 'artifact' | 'export'
    target_id   UUID,
    payload     JSONB,                  -- 入参/出参摘要；★ 密钥、大二进制严禁写入
    cost        DECIMAL(8,4),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_eventlog_project_time ON event_log(project_id, created_at DESC);
```

### 实现 4：认证与多租户隔离（原文档只出现 `get_current_user` 未展开）

- **认证**：JWT（access + refresh），`get_current_user` 依赖注入解析；BYOK key 用 Fernet 加密存储，**永不进日志/SSE/导出包**（对齐规划书 6.3）。
- **多租户隔离**：PostgreSQL Row-Level Security，按 `user_id` / `project_id` 强制隔离；对象存储按用户分桶 + 限时签名 URL；Worker 进程禁止跨项目访问。
- **落点**：`api/deps.py` 出 `get_current_user`；RLS 策略随 Alembic 迁移下发。

### 测试策略（原 `tests/` 空目录，补策略）

| 层级 | 范围 | 重点 |
|------|------|------|
| 单元测试 | `compute_input_hash`、阈值校准 `calibrate_threshold`、规则引擎 | 纯函数，覆盖边界（空上游、参数噪声、冷启动<4张） |
| 集成测试 | API→service→arq→handler（Provider 用 mock 适配器） | 状态机流转、Session 隔离、DB-先写-再广播时序 |
| **一致性引擎回归集** | 固化一批"已知漂移/已知正常"的图像+视频样本 | 每次改阈值/换模型跑该集，防止召回率回退；断言相似度判定与人工标注一致率 ≥ 目标 |

回归样本集是护城河的"金标准"，应随项目长期维护、只增不删。

---

## 九、后续工作

下一步按以下顺序执行：

1. **BOOT-0 仓库启动**（当前唯一任务）—— 建立可运行仓库、本地基础设施和质量门禁。
2. **S0-A / S0-B 双 Spike** —— 分别验证 InsightFace 角色一致性与剪映草稿兼容性；S0-B 不通过则降为 P0.5。
3. **S1 可信基础骨架** → **S2 首帧垂直切片** → **S3 运行时加厚** → **S4 完整生产闭环** → **S5 正式交付硬化**。

本文件与《AI短剧工作台完整实施规划.md》的关系：
- 规划书只保留为早期调研与需求来源，不再定义当前范围、数据模型、技术选型或排期。
- 本文件保存架构决策理由和阶段背景，也不覆盖根目录 `01`–`06` 冻结合同。

实施发生冲突时，以 `01`–`06` 对应主题、`agent.md` 当前任务和已批准 ADR 为准。

---

## 十、架构完善修订（2026-07-13）

> 本节是对前文定稿内容的**替代性补全**。为保持评审历史，原段落不删除；凡本节与第三、四、五、七、八、九节冲突者，均以本节为准。

### 10.1 冻结条件与实施原则 `[修订 2026-07-13｜避免“技术方向确认”被误解为“细节已经可实现”]`

本文件的五层架构、Python/FastAPI/Arq/React 技术基线和“Production Graph 为核心”的方向继续有效。

但 P0 在完成以下 Gate 前不得视为实现规范已冻结：S0-A 视觉一致性 Spike、S0-B 剪映兼容性 Spike，以及 10.2 至 10.7 的 ADR 与集成测试。

**修改原因**：此前“已定稿，后续开发以此为准”覆盖了仍未定义的运行时 Interface、事件可靠性和隔离细节，实施时会迫使开发者临场做高影响决策。

### 10.2 Production Graph 采用“定义—执行—供应商操作—产物”四层模型 `[修订 2026-07-13｜消除 GraphNode 与 GenerationJob 的双重真相]`

```text
GraphVersion
  └─ GraphNode                 图定义：应做什么
       └─ NodeRun              执行尝试：这一次做了什么
            └─ ProviderOperation  外部异步操作：供应商实际做了什么
                 └─ Artifact   不可变产物：这一次产生了什么
```

- `GraphNode`：稳定节点定义、期望输入、最新成功 Run 引用；不承载某次重试的瞬态状态。
- `NodeRun`：`attempt_no`、`idempotency_key`、`status`、开始/结束时间、取消请求时间、错误、实际成本、结果 Artifact 引用、`reused_from_run_id`。状态机至少区分 `queued`、`running`、`cancel_requested`、`cached`、`blocked_budget`、`completed`、`completed_after_cancel`、`failed` 与 `cancelled`。
- `ProviderOperation`：Provider、远端任务 ID、轮询 checkpoint、实际模型、请求摘要和实际计费。
- `Artifact`：内容不可变；任何新输出都创建新的 Artifact，禁止用新文件覆盖旧记录。

`GenerationJob` 作为独立核心模型取消；它的语义分别落入 `NodeRun` 与可选的 `ProviderOperation`。

Production Graph 对 API、Agent、前端和 Worker 只暴露下列 Interface：

```text
create_graph(shot_id, template_version)
plan(graph_id)
run(graph_id, requested_node_ids=None)
rerun(node_id, force=False)
cancel(run_id)
resolve_review(node_id, decision)
get_snapshot(graph_id)
```

调用方不得直接改写节点状态或直接投递 Arq Job。

**修改原因**：原 `GraphNode` 和 `GenerationJob` 同时包含状态、成本、重试与 checkpoint，无法判断哪一个是最终真相。四层模型将复杂行为收敛在 Production Graph Module 内，提高测试性和恢复能力。

### 10.3 DAG 改用显式边、命名端口与不可变版本 `[修订 2026-07-13｜让多媒体生产图具备可表达性和可回滚性]`

`GraphNode.depends_on` 不再作为唯一依赖表达。新增：

```text
GraphVersion
  ├─ GraphNode
  └─ GraphEdge(
       upstream_node_id, downstream_node_id,
       output_port, input_port, position, required
     )
```

- 合成节点通过命名端口接收 `video.main`、`voice.dialogue`、`subtitle.srt`、`music.bgm`。
- 相同输入端口可由 `position` 表示稳定顺序；`required` 决定缺输入时是失败还是跳过。
- 模板升级、分镜图结构修改、人工编辑均创建新的 `GraphVersion`；已执行版本不得原地改变。
- Graph Runner 只运行经无环校验、端口完整性校验和权限校验后的 GraphVersion。

**修改原因**：无序 `depends_on` 不能表达 FFmpeg 等节点的端口和输入顺序，也无法可靠支持图模板升级、人工编辑与回滚。

### 10.4 `input_hash` v2 与缓存合同 `[修订 2026-07-13｜防止错误复用、状态污染和跨项目泄漏]`

`input_hash` 的语义是：**当前 Project、当前 GraphVersion 下，节点的有效输入是否相同**。它不是跨租户的全局内容缓存。

Hash 必须包含：

```text
缓存作用域：project_id + graph_version_id + node_id
节点语义：node_type + executor_id + executor_version + template_version
命名输入：input_port + position + output_port + upstream artifact.file_hash
有效参数：规范化后的 provider/model/采样/提示词/时长/分辨率等
生成上下文：provider 指纹、Prompt 模板版本、注入后的连续性规则版本
```

下列字段不得纳入 Hash：`created_at`、展示名称、`retry_count`、前端排序等不影响输出的噪声。

- `cached` 是一次 `NodeRun` 的结果，不得覆盖 Node 历史上的 `completed` 事实。
- `force=true` 必须创建新的 NodeRun，而非伪造 Hash 变化。
- 强制重跑产生新的 Artifact 后，下游依据新 `file_hash` 失效并按 GraphEdge 级联重跑。
- P0 的缓存只在同一 Project 内生效；禁止默认跨项目复用 BYOK 生成产物。

**缓存命中执行合同：**

- 命中缓存时必须创建新的 `NodeRun(status=cached)`，写入本次 `started_at` / `finished_at` 与 `reused_from_run_id`；后者直接指向实际生成该 Artifact 的源 Run，不形成多跳复用链。
- 缓存 Run 的结果 Artifact 引用必须指向源 Run 的**同一不可变 Artifact**；禁止复制文件或创建伪 Artifact。`GraphNode.latest_successful_run_id` 更新为该缓存 Run，使快照反映本次执行，同时保留源 Run 的可追溯性。
- 缓存命中不得创建 `ProviderOperation`，也不得调用 Provider。缓存 Run 的 `provider_cost` 与 `platform_cost` 均为 `0`；`cost_ledger` 仅对源 `ProviderOperation` 记一次真实成本。缓存节省金额只能作为 `cache_saved_cost` / `avoided_cost_estimate` 指标展示，不得混入实际成本。
- 仅可复用同 Project、已完成、权限仍有效、关联 Artifact 未删除且未隔离的源 Run。Artifact 的删除、冷存储或隔离前必须检查所有 NodeRun、交付包与审核记录引用，避免产生对象不存在的假命中。
- 相同 `project_id + graph_version_id + node_id + input_hash` 的并发请求实施单飞：首个 Run 持有执行权；其余请求等待该 Run、加入同一执行或在其成功后创建 `cached` Run。不得在缓存尚未落库时重复创建 `ProviderOperation`。
- 写入 `node.cached` 事件，至少包含 `run_id`、`reused_from_run_id`、`artifact_id`、`input_hash` 与 `cache_scope`；它不能伪装为新的 `node.completed`，以便准确统计命中率、实际调用量和节省成本。

**修改原因**：原算法对全部上游 `file_hash` 排序，丢失端口与顺序；同时遗漏 Provider、规则、模板和缓存作用域，可能发生静默错命中。此前也未定义缓存命中是否新建 Run、如何关联 Artifact、如何记账以及并发命中如何去重，导致审计、成本与对象生命周期无法闭环。

### 10.5 事件同步改为 Transactional Outbox `[修订 2026-07-13｜修复“数据库提交后、Redis 发布前”仍会丢事件的窗口]`

原“DB 先写，再 Redis publish”的顺序继续保留，但改为以下原子流程：

```text
单个 PostgreSQL 事务：
  1. 写入 GraphNode / NodeRun / Artifact 业务状态
  2. 写入 event_log 审计记录
  3. 写入 outbox_events(event_id, type, payload, published_at=NULL)
  4. COMMIT

独立 Outbox Dispatcher：
  5. 领取未投递事件
  6. 以 event_id 幂等写入 Redis Streams
  7. 标记 published_at；失败则退避重试
```

- `node.completed`、`node.failed`、`export.ready` 等关键事件使用 Redis Streams。
- `node.progress` 等高频可丢事件使用 Pub/Sub。
- SSE 使用 `Last-Event-ID` 补回 Streams 事件；前端随后使相关 TanStack Query 失效并从 API 重取快照。
- PostgreSQL 始终是业务真相源；Redis 仅用于分发和短期回放。

**投递、死信与保留合同：**

- Outbox 的投递语义为 **at-least-once**。Dispatcher 使用 `FOR UPDATE SKIP LOCKED` 与 `leased_until` / `locked_by` 领取事件；若已发布到 Redis 但尚未来得及写入 `published_at`，允许再次投递。所有消费者必须以 `event_id` 去重，不得依赖“恰好一次”。
- `outbox_events` 至少记录 `event_id`、`type`、`schema_version`、`project_id`、`payload`、`attempt_count`、`next_attempt_at`、`leased_until`、`published_at` 与最后错误摘要。payload 只放事件分发所需的最小字段与实体版本；不得默认嵌入完整业务对象、BYOK 密钥、提示词全文或生物特征数据。
- `published_at IS NULL` 的事件永不参与常规清理；按退避策略重试。超过重试上限后，原子转入 `outbox_dead_letters`，保存失败原因和最后一次尝试时间，并产生告警与人工重放入口。
- `published_at IS NOT NULL` 的记录默认保留 **7 天**，以支持 Streams 对账、短期重放和故障排查。每日批处理先导出已投递记录为 Parquet 到 MinIO，再从 PostgreSQL 删除；若合规审计确认 `event_log` 已持久保存所需审计事实，可关闭归档并直接删除。
- `event_log` 的保留期、归档与删除政策独立于 Outbox；Outbox 仅是可靠投递中转，不承担长期审计。清理任务必须输出扫描数、归档数、删除数、最早未投递事件年龄和死信数量等指标。

**修改原因**：若 commit 成功后进程崩溃或 Redis 不可用，原实现无法保证“待发送事件”可恢复。Outbox 将业务状态和待发布事件绑定在同一事务中。此前也没有定义重复投递、失败终态、payload 边界和已投递记录的清理策略，长期运行会造成重复副作用、敏感数据扩散或 PostgreSQL 无界增长。

### 10.6 私有工作区、RLS、SSE 与对象存储形成闭环 `[修订 2026-07-26｜把工作区隔离落到运行时而非描述层]`

新增模型：

```text
User
  └─ Workspace(owner_user_id)
       └─ Project(workspace_id)
```

- API 和 Worker 运行账户不得是 PostgreSQL schema owner、superuser 或带 `BYPASSRLS` 的账户。
- 每个数据库事务使用 `SET LOCAL` 注入当前用户、选中工作区和项目上下文；连接归还池前必须清理。
- RLS policy 同时验证 `Workspace.owner_user_id = current_user_id`、选中工作区和项目范围；同一用户的两个工作区也必须互相隔离。Worker 从持久化的 `NodeRun -> Project -> Workspace` 链重建上下文，不信任队列消息中的资源 ID、工作区或对象路径。
- P0 使用同站 `HttpOnly + Secure` 会话 Cookie 与 CSRF 防护。SSE 不通过 URL 传递长期 JWT。
- SSE 统一事件 Envelope：`id / type / occurred_at / project_id / entity(type,id,version) / payload`。
- MinIO 使用 `workspace/{workspace_id}/project/{project_id}/artifact/{artifact_id}/{content_hash}` 对象键；预签名 URL 限时、单对象、单动作。
- 上传对象先进入隔离区，完成 MIME 嗅探、尺寸/时长校验和安全扫描后再转入正式路径。

**修改原因**：原方案仅写“RLS + user_id/project_id + 预签名 URL”，未处理连接池上下文、Worker 越权、EventSource 认证限制及上传文件安全。

### 10.7 BYOK、自动修复与生物特征处理的运行规则 `[修订 2026-07-13｜限制成本风险并补齐失败分类]`

- Provider 降级候选池仍等于“用户已配置 Key”与“具备所需能力”的交集。
- 本地 ComfyUI 只能在部署方显式启用、相关模型许可已审计且用户允许本地执行时作为兜底。
- 每个 Node 配置 `max_auto_attempts`、预算上限、退避策略和人工审核阈值；耗尽后进入 `needs_review`，不得无限重生成。
- InsightFace 结果统一分类为：`matched`、`below_threshold`、`no_face`、`multiple_faces`、`low_quality`、`provider_error`。
- 仅可恢复的类别可触发自动重生成；无脸、多脸或低质量优先进入人工处理或不同修复策略。
- 角色参考图、人脸嵌入和相关审核记录必须定义授权来源、最短保留期、加密存储、访问控制和删除流程；第三方模型及权重另行完成许可证审计。

**修改原因**：仅以“低于阈值就重生成”会混淆不可恢复异常并造成 BYOK 成本失控；人脸嵌入也需要独立的数据治理约束。

### 10.8 导出范围与可行性 Spike `[修订 2026-07-13｜将私有格式风险从交付承诺中隔离]`

确定性 P0 交付调整为：

```text
MP4 + SRT + 素材包 + 时间线 JSON
```

剪映草稿保留为候选 P0 功能，但必须先通过 **S0-B 兼容性 Spike**：

```text
□ 明确目标剪映版本和操作系统范围
□ 手工创建最小草稿，记录媒体、轨道、字幕和时间线字段
□ 生成等价草稿并在干净机器导入
□ 固化 golden fixture 与兼容性回归
□ 任一核心能力不稳定时，剪映草稿降为 P0.5，不阻塞主闭环
```

DaVinci XML、EDL、AAF 仍按原 P1/P2 规划推进；PR 工程继续不做。

**修改原因**：原方案将剪映草稿作为 P0 确定承诺，却没有定义目标版本、兼容性样本、回归验证和降级策略。

### 10.9 S0 验收改为双 Spike，阶段计划重排 `[修订 2026-07-13；执行同步 2026-07-20｜用数据验证护城河和交付风险]`

| 阶段 | 周期 | 核心任务 | 验收 Gate |
|---|---:|---|---|
| **BOOT-0：仓库启动** | 按 Gate | 可运行仓库骨架、本地基础设施与质量门禁 | Compose 配置、API/Worker/前端壳、静态检查、测试、构建和目录检查通过 |
| **S0-A：视觉一致性 Spike** | 3 天 | 评估同/异角色与异常样本的相似度分布 | 至少 20 对同角色、20 对异角色、10 个异常样本；输出 FAR、FRR、耗时和成本 |
| **S0-B：剪映兼容性 Spike** | 2 天 | 验证最小草稿导入 | 干净环境可打开，媒体/轨道/字幕正确；不通过则降 P0.5 |
| **S1：可信基础骨架** | 2 周 | RLS、Outbox、Graph 模型、Creation Experience Interface、统一项目路由 | 迁移、隔离、Outbox 重放、队列启动与同项目双入口打开均通过 |
| **S2：快速模式首帧垂直切片** | 2 周 | 文本→计划确认→首帧→相似度/成本→同项目工作台切换 | 不靠人工搬运数据即可查看同一 Run；API→Graph→Worker→Adapter→Artifact→SSE 全链路可用；不得视为 P0 完成 |
| **S3：Production Runtime 加厚** | 2.5 周 | DAG、缓存、取消、重试、预算和恢复 | 局部修改只影响正确下游，断点恢复与幂等测试通过 |
| **S4：专业工作台与完整生产闭环** | 3 周 | 项目/资产/剧本/分镜、`shot-p0-v1` 全节点、规则、质检与个人审核 | 10 Shot 可生成、审核、修复和局部重跑；人工锁定不被 Agent 覆盖 |
| **S5：交付与集成硬化** | 2.5 周 | MP4/SRT/素材包/时间线 JSON、部署恢复、压测与安全回归 | 10 Shot 流程无阻断，正式交付可复现；通过后才可宣布 P0 MVP 完成 |

S0-A 具体要求：不得只观察“5 张同角色图是否大于 0.7”；必须同时衡量不同角色误通过、同角色误拒绝、无脸/多脸/遮挡分类、人工标注一致率、平均耗时和单次修复成本。

**修改原因**：此前 S0 的样本量和判定标准不足以证明阈值可用于生产；原排期也未为剪映兼容性提供独立的证伪路径。

### 10.10 取消、预算、Provider 入站事件与 Artifact 生命周期 `[修订 2026-07-13｜避免“停止按钮”“成本上限”和“异步回调”在竞态下失真]`

**取消与重试合同：**

- `cancel(run_id)` 必须幂等。它先将可执行 Run 原子置为 `cancel_requested`，记录请求人、时间和原因，写入 `node.cancel_requested`，并立即阻止该 Run 调度新的下游节点；不得仅因用户点击停止就提前宣称已取消。
- 尚未向 Provider 发出的 Run 可直接终止为 `cancelled`，且 Dispatcher 在实际发出请求前必须再次检查 Run 状态。已创建远端任务的 Run 则记录取消尝试、响应与远端任务 ID；Provider 支持取消时必须调用其取消接口。
- 轮询或回调与取消请求竞争时，若远端任务已先成功，Run 终态为 `completed_after_cancel`。该 Artifact 仅用于对账和争议处理，不更新 `latest_successful_run_id`、不进入缓存、也不自动触发下游；只有具备权限的人工审核显式采纳后，才可转为后续图执行的输入。
- `cancelled` 与 `completed_after_cancel` 均不得自动重试。用户重新执行必须新建 Run 和新的幂等键；已发生的实际费用仍按 Provider 回传或可审计估算入账，取消不是免单标记。

**预算预占与结算合同：**

- 在创建真实 `ProviderOperation` 前，必须在同一事务中为该 Run 创建预算预占。预占额为该节点在当前模型、分辨率、时长和允许重试次数下的最坏可接受费用；`cached`、`blocked_budget`、取消前未发出的 Run 不创建预占。
- 若可用预算不足，Run 进入 `blocked_budget` 并写入 `node.blocked_budget`，不得调用 Provider，也不得以“事后超支”为常规控制方式。并发 Run 通过原子扣减可用额度，避免分别检查后共同超支。
- 成功、失败和取消完成后均需结算：真实费用以不可变 `cost_ledger` 分录记录，未使用预占额释放；晚到的账单、汇率或计价修正只能追加 adjustment 分录，禁止改写已结算历史。
- 若真实费用超过预占，系统必须记录超额原因、冻结该 Project 后续真实 Provider 调度并通知管理员；已经发生的费用照实入账。所有金额同时保存原始币种/单位、计价快照和统一展示金额，BYOK 估算与平台实际收入不得混为同一指标。

**Provider 回调与轮询合同：**

- Provider Webhook 入口只负责验证签名、时间戳和重放窗口，并按 `provider + provider_event_id`（无事件 ID 时按规范化 payload 哈希）唯一写入 `provider_inbox`；验证失败不得泄露任务是否存在。原始 payload 按最小必要原则加密短期保存，禁止把密钥写入日志。
- 入站事件只能通过已保存的 `ProviderOperation.remote_task_id` 关联 Project 与 Run，绝不信任回调 payload 中声称的租户、用户、对象路径或费用。处理 Worker 从 Inbox 消费后再推进状态、结算和写 Outbox；Webhook Handler 不直接广播 SSE/Redis。
- 轮询和回调必须调用同一条件状态迁移函数，并使用版本号或条件更新处理重复、乱序和并发。终态重复事件只补充可审计的计价信息，不得再次创建 Artifact、`cost_ledger` 分录或下游执行。
- Artifact 只有在下载完成、内容哈希、MIME/尺寸/时长和安全检查均通过后，才可与 NodeRun 成功状态、`event_log` 和 Outbox 在同一业务事务中提交。

**Artifact 生命周期合同：**

- Artifact 记录与二进制内容均不可变。对象状态至少区分 `quarantined`、`available`、`cold`、`delete_requested` 与 `deleted`；隔离对象不得被消费或命中缓存。
- 缓存命中只可引用可在线读取的 `available` Artifact。处于 `cold` 的对象必须先完成校验后的回温，回温失败则作为缓存未命中处理；不得创建指向不可访问对象的 `cached` Run。
- 删除采用“逻辑删除请求—引用与保留期检查—物理删除”三阶段。GC 必须检查 NodeRun、交付包、审核记录、人工固定引用及 legal hold；仍被引用或仍在最短保留期内的 Artifact 只能拒绝删除或延期处理。
- 物理删除后仍保留最小 tombstone、内容哈希、删除原因和审计记录。回温、复制和删除都必须校验内容哈希，并写入独立生命周期审计事件。

**修改原因**：原文虽列出“取消、重试、预算和恢复”为 S3 工作项，但没有定义取消与完成竞争、预算并发超支、回调重复乱序及产物冷存储/删除的最终语义。这些边界一旦留给各 Worker 自行判断，会造成已取消结果误入缓存、Provider 重复计费、回调越权和 Artifact 假命中。
### 10.11 项目结构与测试范围的替代要求 `[修订 2026-07-13｜把关键运行时能力固化为可维护的 Module]`

后端目录的核心 Module 以职责收敛为准：

```text
production/  GraphVersion / GraphNode / GraphEdge / NodeRun / scheduler
execution/   NodeExecutor / ProviderOperation / retry / cancellation
access/      authentication / authorization / RLS context
assets/      reference set / object lifecycle
consistency/ continuity / face / visual QA
events/      event_log / outbox / Streams / SSE
delivery/    FFmpeg / subtitle / export package
```

以下测试在 S1/S2 即纳入 CI：

| 测试层级 | 必测行为 |
|---|---|
| 单元 | Hash 命名端口顺序、DAG 无环与输入完整性、参数噪声、阈值冷启动、脱敏、Outbox payload 脱敏与 schema_version |
| 集成 | 幂等提交、取消/完成竞态、取消后阻断下游、重试、预算预占并发控制、缓存命中新建 `NodeRun` 且不创建 `ProviderOperation`、并发同 Hash 单飞、Outbox 重放/重复投递去重、SSE 断线恢复、Graph 快照重取 |
| 成本与生命周期 | `cost_ledger` 对源 `ProviderOperation` 仅记一次、缓存 Run 成本为零、预算预占/释放/超额 adjustment、取消后实际费用结算、缓存引用 Artifact 时拒绝误删、冷存储回温失败不产生假命中 |
| 事件运维 | 未投递事件不清理、重试耗尽转死信、已投递事件 7 天归档或删除、归档失败不删除源记录 |
| 隔离 | RLS 越权拒绝、连接池上下文清理、Worker 跨项目 Artifact 拒绝、对象 URL 范围 |
| Provider 契约 | 创建、轮询、取消、限流、错误归一化、实际成本、Webhook 签名验证、重放去重、乱序回调与轮询竞态 |
| 回归 | 一致性标注集、MP4/SRT/时间线 JSON 与可选剪映 golden fixture |

**修改原因**：原目录按技术层分割较细，Production Graph、执行、事件和权限容易横向穿透；按深 Module 收敛后，调用者只需要理解少量稳定 Interface。

### 10.12 修订后的后续动作 `[修订 2026-07-13；执行同步 2026-07-20｜将设计结论转为可验证 Gate]`

1. 先执行 `agent.md` 的 `Task BOOT-0.1`；用 mock 和本地基础设施通过仓库启动 Gate，不接入真实 Provider。
2. BOOT-0 通过后完成 S0-A、S0-B，并保存可复现实验报告、样本清单和结论；S0-B 可因外部 GUI 环境延后，不阻断主交付。
3. 在对应能力实现前，为 10.2 至 10.10 建立所需 ADR：执行模型、DAG/缓存、Outbox、隔离/SSE、密钥/自动修复、交付范围，以及取消/预算/Provider 入站事件/Artifact 生命周期；不得为追求“设计齐全”一次铺满未进入阶段的实现。
4. S1 通过 RLS、Outbox 重放、死信与清理演练、缓存命中、预算预占和 Graph 数据模型 Gate 前，不接入真实 Provider。
5. S2 仅接一个真实 Image Provider；先打穿一条可审计的 Keyframe 切片，再在 S4 补齐固定 DAG、S5 完成交付硬化。
6. 每阶段更新 SBOM、许可证白名单、第三方 NOTICE、风险台账和验收记录。


