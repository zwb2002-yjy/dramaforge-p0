# DramaForge V1 实施方案

**文档日期**: 2026-09-07  
**项目状态**: dev 分支，V1 Goal GOAL_BLOCKED  
**基线 commit**: d024b2d  
**方案定位**: 基于当前项目实际情况的务实补全方案

---

## 一、当前项目架构梳理

### 1.1 已有核心能力（保留复用）

#### 后端架构
```
✅ 数据层
- PostgreSQL 15 + Alembic (55 个 migration，最新 20260903_0055)
- RLS 行级安全 (Workspace 隔离)
- Project / Scene / Shot / Asset / AssetVersion
- ScriptDocument / Episode 结构

✅ 执行层
- Production Graph (ProductionGraph + GraphNode + GraphEdge)
- GraphVersion (版本与物化)
- NodeRun (局部节点执行 + checkpoint)
- Outbox + Redis + Arq Workers (异步执行)
- ProviderOperation (请求血缘 + 幂等 + 恢复)

✅ Provider 层 (完整插件化体系)
- ProviderPlugin (Agnes / MiniMax / Volcengine)
- ModelCatalogEntry (不可变能力声明)
- ProviderConnection (Workspace 账号绑定)
- ProviderModelBinding (模型执行绑定)
- ProductionModelProfile (项目级模型方案)
- Compiler + Runtime (原生请求编译)
- EffectiveRequest (实际请求快照)

✅ Director 层
- DirectorThread (对话线程)
- DirectorProposal (AI 提案)
- DirectorProposalItem (typed command + partial apply)
- DirectorAutonomy (AUTO/ASSIST/MANUAL)
- Proactive Recommendation (主动建议)

✅ 资产与版本
- Asset / AssetVersion / AssetVersionReference
- ShotReferenceBinding (镜头引用绑定)
- Canvas Revision (画布版本控制)

✅ 编辑与交付
- EditSession / EditingAdapter
- Timeline (时间线)
- Director Editing Suggestion
- Final Film (成品血缘)
```

#### 前端架构
```
✅ 基础框架
- React 18 + TypeScript
- TanStack Router (路由)
- TanStack Query (服务端状态)
- Zustand (UI 状态)
- Tailwind CSS + Radix UI

✅ 已有页面/组件
- Project Workspace Shell
- Scene Workbench (Canvas + Candidate Tray + Shot Strip)
- Director Board 2D (场景布局可视化)
- Director Sidebar
- Shot Director Suggestion Panel
- Asset Cards Panel
- Model Profile Settings
- Provider Connection Panel
- Editing Workspace
- Experiment Compare
```

### 1.2 当前 V1 Goal 状态

**Goal**: DramaForge V1 统一创作主链

**状态**: GOAL_BLOCKED

**已完成 Task**:
- ✅ G0: 权威基线与架构登记
- ✅ G1: Story Authoring Proposal Chain
- ✅ G2: CreativeTemplate 与 ProjectCreativeProfile
- ✅ G3: DirectorAutonomy
- ✅ G4: Proactive Director Recommendation
- ✅ G5: Creation UX 与统一 Canvas
- ✅ G6: OpenCut Director 主动剪辑建议

**进行中 Task**:
- ⏳ G7: 统一主链 E2E 与 current-HEAD 双路径真实 Provider Golden
- ⏳ G8: Current-HEAD Release Candidate Gate

**阻塞原因**:
> Final Film Timeline 真渲染、Worker 异步链、重试语义、前端等待/dirty gate 与 current-HEAD 证据仍未闭环

---

## 二、核心缺口分析

### 2.1 后端缺口

#### Priority A: V1 Goal 阻塞项

| 缺口 | 当前状态 | 影响 | 优先级 |
|------|---------|------|--------|
| **Final Film Timeline 真渲染** | G7-D/G7-E 未完成 | 无法生成最终成片 | P0 |
| **Worker 异步链闭环** | 重试语义、状态传播不完整 | 任务失败恢复不可靠 | P0 |
| **前端等待机制** | 与后端异步状态不对齐 | 用户体验差，状态不一致 | P0 |
| **Current-HEAD Golden 证据** | 旧证据绑定过时 commit | 无法发布 | P0 |

#### Priority C: 业务功能缺口

| 缺口 | 当前状态 | 是否必需 | 优先级 |
|------|---------|---------|--------|
| **资产状态时间线** | `asset_state_timeline` 表不存在 | 视项目决定 | P1 |
| **生成前约束注入** | 无 Prompt 约束拼接机制 | 一致性保证弱 | P1 |
| **MP4 + SRT 导出** | delivery 模块存在但功能不完整 | 必需（最终交付） | P1 |
| **Agnes + MiniMax 端到端** | 单独能用，未验证完整链路 | 必需（Golden 需要） | P0 |

#### 明确不做（首版）

| 功能 | 原因 |
|------|------|
| ❌ Face Embedding 自动人脸检测 | README 明确："首版不集成人脸 embedding、生物特征识别或相似度阈值" |
| ❌ 生成后自动质检（视觉 LLM） | 需外部视觉模型，成本高，人工验收替代 |
| ❌ 成本追踪与预算守卫 | V1 单用户可自控，后续商业化再加 |
| ❌ 本地 ComfyUI 部署 | 先跑通云端 API，本地部署非首要 |
| ❌ 剪映草稿 / DaVinci XML 导出 | 仅 MP4+SRT，复杂格式后续迭代 |

### 2.2 前端缺口

#### 严重缺口

| 缺口 | 表现 | 影响 | 优先级 |
|------|------|------|--------|
| **Agent Runtime 缺失** | 前端无统一 Agent 执行状态管理 | Director 建议无法实时反馈 | P0 |
| **NodeRun 状态展示** | 无 Production Graph 执行进度 UI | 用户不知道生成进行到哪一步 | P0 |
| **异步任务等待机制** | 轮询逻辑不统一，dirty gate 未实现 | 状态不同步，用户体验差 | P0 |
| **Director Proposal Apply** | partial apply 逻辑不完整 | 用户无法灵活采纳 AI 建议 | P1 |
| **Artifact 预览** | 生成产物无统一预览组件 | 查看结果需跳转，流程割裂 | P1 |

#### 设计一致性问题

| 问题 | 当前状况 | 建议 |
|------|---------|------|
| **状态管理混乱** | TanStack Query + Zustand 职责不清 | 明确：服务端状态用 Query，UI 状态用 Zustand |
| **错误处理不统一** | 各模块自行处理错误 | 统一 ErrorBoundary + Toast 通知 |
| **加载状态缺失** | 部分操作无 Loading 提示 | 补充 Skeleton / Spinner |
| **实时更新机制** | SSE 事件流未完整连接到 UI | 实现 SSE → Query invalidation |

---

## 三、分阶段实施计划

### Phase 0: 环境验证与基线确认（1 天）

**目标**: 确保开发环境可用，理解当前阻塞点

**任务清单**:
- [ ] 启动完整 Docker Compose 栈
- [ ] 运行质量门禁 (`scripts/run_quality_in_docker.ps1`)
- [ ] 阅读 G7/G8 Task Contract 详细内容
- [ ] 运行现有前端，复现阻塞问题
- [ ] 确认 Agnes + MiniMax API 密钥可用

**验收标准**:
- Docker 栈健康检查通过
- 质量门禁全绿
- 能访问前端 `http://localhost:8080`
- 明确 G7/G8 具体技术阻塞点

---

### Phase 1: 解除 V1 Goal 阻塞（优先级 A，2-3 周）

#### 1.1 后端：Final Film Timeline 真渲染（1 周）

**目标**: 实现从 Shot → Composite → Final Film 的完整渲染链

**任务清单**:
- [ ] 分析现有 `backend/app/delivery/` 模块
- [ ] 补全 Final Film Graph Node 定义
- [ ] 实现 FFmpeg 合成 Worker（Video + Audio + Subtitle → MP4）
- [ ] 实现 SRT 字幕生成（从 Shot dialogue 提取）
- [ ] 测试 Shot 级别产物 → Timeline → Final Film 血缘

**技术方案**:
```python
# backend/app/delivery/final_film.py
class FinalFilmNode:
    node_type = "final_film_composite"
    executor = "tool:ffmpeg"
    
    async def execute(self, inputs: dict) -> Artifact:
        # inputs: {shots: [VideoArtifact, ...], timeline: TimelineSpec}
        # 1. 按 timeline 顺序拼接视频
        # 2. 叠加字幕轨（SRT）
        # 3. 输出 MP4 + SRT 独立文件
        pass
```

**验收标准**:
- 能从 3 个 Shot（Video + Audio）合成一个 Final Film MP4
- MP4 包含字幕烧录或独立 SRT 文件
- Artifact 表正确记录血缘链

#### 1.2 后端：Worker 异步链闭环（1 周）

**目标**: 修复 NodeRun 重试语义、状态传播、依赖检查

**任务清单**:
- [ ] 审计 `backend/app/execution/` 当前 NodeRun 逻辑
- [ ] 补全 NodeRun 状态机（pending → running → completed/failed）
- [ ] 实现 GraphEdge 依赖检查（上游未完成，下游不启动）
- [ ] 实现 NodeRun 失败重试（指数退避，最多 3 次）
- [ ] 增强 Outbox Dispatcher 日志（追踪事件派发链）

**技术方案**:
```python
# backend/app/execution/runner.py
async def run_node(node_run: NodeRun, graph_version: GraphVersion):
    # 1. 检查上游依赖是否全部 completed
    upstream_ready = await check_upstream_dependencies(node_run)
    if not upstream_ready:
        return  # 等待上游
    
    # 2. 更新状态为 running
    node_run.status = "running"
    await db.commit()
    
    # 3. 执行 Executor
    try:
        artifact = await execute_node(node_run)
        node_run.status = "completed"
        node_run.artifact_id = artifact.id
    except Exception as e:
        node_run.status = "failed"
        node_run.error_message = str(e)
        if node_run.retry_count < 3:
            # 重新入队，指数退避
            await enqueue_retry(node_run, delay=2 ** node_run.retry_count)
    
    await db.commit()
```

**验收标准**:
- Shot Node 失败后自动重试 3 次
- 上游 Node 未完成时，下游 Node 不执行
- Outbox 事件正确触发前端状态更新

#### 1.3 前端：Agent Runtime + NodeRun 状态展示（1 周）

**目标**: 统一 Agent 执行状态管理，实时展示 Production Graph 进度

**任务清单**:
- [ ] 创建 `AgentRuntimeProvider` (React Context)
- [ ] 实现 SSE 连接 + TanStack Query invalidation
- [ ] 创建 `ProductionGraphProgress` 组件
- [ ] 创建 `NodeRunStatusBadge` 组件
- [ ] 实现 dirty gate 检查（本地编辑 vs 服务端状态）

**技术方案**:
```typescript
// frontend/src/contexts/AgentRuntimeContext.tsx
export function AgentRuntimeProvider({ children }) {
  const queryClient = useQueryClient();
  
  useEffect(() => {
    const eventSource = new EventSource('/api/v1/events');
    
    eventSource.addEventListener('node.started', (e) => {
      const data = JSON.parse(e.data);
      queryClient.invalidateQueries(['nodeRun', data.nodeRunId]);
    });
    
    eventSource.addEventListener('node.completed', (e) => {
      const data = JSON.parse(e.data);
      queryClient.invalidateQueries(['nodeRun', data.nodeRunId]);
      queryClient.invalidateQueries(['artifact', data.artifactId]);
    });
    
    return () => eventSource.close();
  }, []);
  
  return <AgentRuntimeContext.Provider value={{}}>{children}</AgentRuntimeContext.Provider>;
}

// frontend/src/components/production/ProductionGraphProgress.tsx
export function ProductionGraphProgress({ graphVersionId }: { graphVersionId: string }) {
  const { data: nodes } = useQuery(['graphNodes', graphVersionId], fetchGraphNodes);
  
  return (
    <div className="space-y-2">
      {nodes?.map(node => (
        <div key={node.id} className="flex items-center gap-2">
          <NodeRunStatusBadge status={node.status} />
          <span>{node.display_name}</span>
          {node.status === 'running' && <Spinner />}
        </div>
      ))}
    </div>
  );
}
```

**验收标准**:
- 点击"生成"后，实时看到 Keyframe → Video → Composite 进度
- Node 失败时显示错误提示，可重试
- 本地修改 Shot 后，dirty gate 提示"未保存"

#### 1.4 Agnes + MiniMax 端到端验证（融入上述任务）

**目标**: 确保 Agnes 图像 + MiniMax 视频在真实 Golden 中可用

**任务清单**:
- [ ] 验证 Agnes 图像生成 API 调用
- [ ] 验证 MiniMax 图生视频 API 调用
- [ ] 完整链路：Shot Design → Agnes Keyframe → MiniMax Video → Final Film
- [ ] 记录 Golden 证据（截图 + Artifact 血缘）

**验收标准**:
- 从剧本到最终 MP4 的完整流程可运行
- 生成的 MP4 包含 Agnes 生成的关键帧 → MiniMax 生成的视频
- 证据报告绑定 current commit SHA

---

### Phase 2: 业务功能补全（优先级 C，2-3 周）

#### 2.1 资产状态时间线（可选，1 周）

**评估决策**: 

**如果做**:
- 创建 `asset_state_timeline` 表
- 记录角色服装、道具持有在各 Shot 的变化
- UI：Asset Timeline 可视化

**如果不做**:
- 依赖用户人工审核 + Director 建议
- 文档说明："一致性由用户在试拍中验收"

**建议**: 
- 评估 V1 用户实际需求
- 如用户反馈"经常忘记前后镜头服装"，则做
- 否则，V1 暂不做，后续迭代

#### 2.2 生成前约束注入（1 周）

**目标**: 在 Prompt 中注入上游 Shot 的资产状态

**任务清单**:
- [ ] 实现 `ContinuityConstraintBuilder`
- [ ] 查询上游 Shot 的角色、场景、道具状态
- [ ] 构造约束 Prompt 片段（如："角色穿白西装，手持合同"）
- [ ] 在 Provider Compiler 中注入约束到最终 Prompt

**技术方案**:
```python
# backend/app/consistency/constraint_builder.py
class ContinuityConstraintBuilder:
    async def build_for_shot(self, shot: Shot) -> str:
        """构造当前 Shot 的一致性约束 Prompt"""
        # 1. 查询上一个 Shot（如果存在）
        prev_shot = await get_previous_shot(shot)
        if not prev_shot:
            return ""
        
        # 2. 提取资产状态
        constraints = []
        for char_id in shot.characters:
            char = await get_character(char_id)
            # 从 prev_shot 的 Artifact 或 design_state 提取状态
            state = extract_character_state(prev_shot, char_id)
            if state.get("costume"):
                constraints.append(f"角色 {char.name} 穿着 {state['costume']}")
        
        # 3. 返回约束文本
        return "\n".join(constraints)

# backend/app/providers/compiler.py (修改)
async def compile_prompt(self, shot: Shot, ...) -> str:
    base_prompt = shot.visual_description
    
    # 注入一致性约束
    constraints = await ContinuityConstraintBuilder().build_for_shot(shot)
    if constraints:
        final_prompt = f"{constraints}\n\n{base_prompt}"
    else:
        final_prompt = base_prompt
    
    return final_prompt
```

**验收标准**:
- 生成 Shot #2 时，Prompt 自动包含 Shot #1 的角色服装
- 用户可在 UI 查看"约束来源"（哪个 Shot 提供的状态）
- 可选：用户可手动编辑或禁用某条约束

#### 2.3 前端设计问题修复（1 周）

**目标**: 统一状态管理、错误处理、加载状态

**任务清单**:
- [ ] 明确 TanStack Query vs Zustand 职责边界
  - Query: 服务端状态（Project / Shot / Artifact / NodeRun）
  - Zustand: UI 状态（侧边栏展开、选中项、布局偏好）
- [ ] 创建统一 `ErrorBoundary` + `Toast` 通知系统
- [ ] 补充 Loading 状态（Skeleton / Spinner）
- [ ] 实现 Artifact 预览统一组件
- [ ] 优化 Director Proposal Apply 交互

**技术方案**:
```typescript
// frontend/src/stores/uiStore.ts (Zustand)
export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  selectedShotId: null,
  layoutMode: 'canvas-first',
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  selectShot: (id) => set({ selectedShotId: id }),
}));

// frontend/src/hooks/useShot.ts (TanStack Query)
export function useShot(shotId: string) {
  return useQuery({
    queryKey: ['shot', shotId],
    queryFn: () => api.getShot(shotId),
    staleTime: 5000, // 5s 内不重复请求
  });
}

// frontend/src/components/shared/ErrorBoundary.tsx
export function ErrorBoundary({ children }) {
  return (
    <ReactErrorBoundary
      fallbackRender={({ error, resetErrorBoundary }) => (
        <div className="p-4">
          <h2>出错了</h2>
          <pre>{error.message}</pre>
          <button onClick={resetErrorBoundary}>重试</button>
        </div>
      )}
    >
      {children}
    </ReactErrorBoundary>
  );
}

// frontend/src/components/artifacts/ArtifactPreview.tsx
export function ArtifactPreview({ artifactId }: { artifactId: string }) {
  const { data: artifact, isLoading } = useQuery(['artifact', artifactId], fetchArtifact);
  
  if (isLoading) return <Skeleton className="h-64" />;
  
  if (artifact.artifact_type === 'image') {
    return <img src={artifact.storage_url} alt="Preview" />;
  } else if (artifact.artifact_type === 'video') {
    return <video src={artifact.storage_url} controls />;
  }
  return <p>不支持的文件类型</p>;
}
```

**验收标准**:
- 所有异步操作有 Loading 提示
- 错误统一显示 Toast 通知，不崩溃
- Artifact 点击后弹出预览 Modal
- Director Proposal 可逐项采纳或拒绝

---

### Phase 3: 发布准备（优先级 A，1 周）

#### 3.1 Current-HEAD Golden 重跑

**目标**: 从 current commit 重新收集真实 Provider 生成证据

**任务清单**:
- [ ] 确保 Phase 1 所有修复已合并到 dev
- [ ] 从干净 worktree 执行 `docs/runbooks/release-gate-board.md`
- [ ] 运行完整流程：Template Start → Story → Scene → Shot → Agnes → MiniMax → Final Film
- [ ] 截图每个关键步骤
- [ ] 记录 Artifact 血缘链
- [ ] 绑定 commit SHA、dirty 状态、环境信息

**验收标准**:
- Golden 证据报告位于 `tmp/p0-evidence/<current-sha>/`
- 包含：
  - 前端截图（创建项目 → Canvas → 生成结果 → Final Film）
  - 后端日志（NodeRun 状态、ProviderOperation 请求/响应）
  - Artifact 元数据（storage_path、file_hash、血缘关系）
  - 环境信息（commit SHA、Python/Node 版本、Provider 版本）
- 所有 Gate 通过，无 FAIL 或 BLOCKED

#### 3.2 文档更新

**任务清单**:
- [ ] 更新 README.md（移除过时信息，补充 V1 状态）
- [ ] 更新 `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
  - 状态：GOAL_BLOCKED → GOAL_DONE
  - 更新 Task 状态表
- [ ] 创建 `V1-RELEASE-NOTES.md`（新功能、已知限制、升级指南）
- [ ] 补充 Runbook（开发环境搭建、常见问题排查）

**验收标准**:
- README 准确描述 V1 能力边界
- V1 Release Notes 明确列出：
  - ✅ 已实现功能（完整创作主链、Agnes+MiniMax、Director 辅助）
  - ⚠️ 已知限制（无自动人脸检测、无成本追踪、仅 MP4 导出）
  - 📋 升级路径（从旧版本迁移指南，如有）

---

## 四、技术实现要点

### 4.1 Production Graph 增量重跑验证

**问题**: 外部文档强调 Production Graph 支持"改字幕不重生成视频"，需验证

**验证方案**:
```python
# 测试：修改 Subtitle Node 的输入
shot = await get_shot(shot_id)
graph_version = await get_graph_version(shot.graph_id)

# 1. 所有 Node 初始为 completed
assert all(n.status == 'completed' for n in graph_version.nodes)

# 2. 修改 Subtitle 输入
subtitle_node = find_node(graph_version, 'subtitle')
subtitle_node.input_spec['text'] = "新字幕"
subtitle_node.status = 'stale'  # 标记过期

# 3. 传播 stale 到下游
for downstream in subtitle_node.downstream:
    downstream.status = 'stale'

# 4. 重跑：只有 Subtitle + Composite + Export 执行
# Keyframe / Video / Voice 保持 completed（命中缓存）
await rerun_graph(graph_version)

# 5. 验证
assert find_node(graph_version, 'keyframe').status == 'cached'  # 未重跑
assert find_node(graph_version, 'video').status == 'cached'     # 未重跑
assert find_node(graph_version, 'subtitle').status == 'completed'  # 重跑了
assert find_node(graph_version, 'composite').status == 'completed'  # 重跑了
```

**如果当前未实现**:
- 补充 `status='cached'` 状态
- 实现 `input_hash` 计算与比对
- 实现 stale 传播逻辑

### 4.2 Provider Compiler 约束注入

**关键点**: 约束 Prompt 必须在 Compiler 层注入，不能在 UI 层拼接

**错误做法**:
```typescript
// ❌ 前端拼接 Prompt（绕过 Compiler，无法追溯）
const prompt = `${constraints}\n\n${shot.visual_description}`;
await api.generateKeyframe({ shotId, prompt });
```

**正确做法**:
```python
# ✅ 后端 Compiler 注入（有 EffectiveRequest 记录）
class AgnesImageCompiler:
    async def compile(self, shot: Shot, ...) -> dict:
        # 1. 获取约束
        constraints = await get_continuity_constraints(shot)
        
        # 2. 构造 Prompt
        prompt = self._build_prompt(shot.visual_description, constraints)
        
        # 3. 编译为 Agnes 原生请求
        request = {
            "model": "agnes-3.0",
            "prompt": prompt,
            "size": "1024x1024",
            ...
        }
        
        # 4. EffectiveRequest 记录完整请求
        return request
```

### 4.3 前端 SSE 事件流

**现有问题**: SSE 连接可能未完整消费或未触发 Query invalidation

**修复方案**:
```typescript
// frontend/src/hooks/useProductionEvents.ts
export function useProductionEvents(projectId: string) {
  const queryClient = useQueryClient();
  
  useEffect(() => {
    const eventSource = new EventSource(`/api/v1/projects/${projectId}/events`);
    
    // Node 启动
    eventSource.addEventListener('node.started', (e) => {
      const { nodeRunId, graphVersionId } = JSON.parse(e.data);
      queryClient.invalidateQueries(['graphNodes', graphVersionId]);
      queryClient.setQueryData(['nodeRun', nodeRunId], (old: any) => ({
        ...old,
        status: 'running',
      }));
    });
    
    // Node 完成
    eventSource.addEventListener('node.completed', (e) => {
      const { nodeRunId, graphVersionId, artifactId } = JSON.parse(e.data);
      queryClient.invalidateQueries(['graphNodes', graphVersionId]);
      queryClient.setQueryData(['nodeRun', nodeRunId], (old: any) => ({
        ...old,
        status: 'completed',
        artifact_id: artifactId,
      }));
      // 预取 Artifact 数据
      queryClient.prefetchQuery(['artifact', artifactId], () => fetchArtifact(artifactId));
    });
    
    // Node 失败
    eventSource.addEventListener('node.failed', (e) => {
      const { nodeRunId, error } = JSON.parse(e.data);
      queryClient.setQueryData(['nodeRun', nodeRunId], (old: any) => ({
        ...old,
        status: 'failed',
        error_message: error,
      }));
      toast.error(`节点执行失败: ${error}`);
    });
    
    return () => eventSource.close();
  }, [projectId]);
}
```

---

## 五、风险与缓解

### 5.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|-----|------|------|---------|
| Worker 异步链修复复杂度高 | 延期 1-2 周 | 中 | 增量修复，先保证主路径，边缘 case 后续迭代 |
| Agnes/MiniMax API 不稳定 | Golden 收集失败 | 中 | 失败重试、降级到 Fake Provider 演示 |
| FFmpeg 合成兼容性问题 | Final Film 生成失败 | 低 | 预先测试多种格式，使用保守参数 |
| 前端状态管理重构工作量大 | 延期 | 中 | 先修最严重问题，非阻塞问题后续优化 |

### 5.2 人力风险

| 风险 | 缓解措施 |
|-----|---------|
| 单人开发，阻塞点多 | 优先级严格排序，A > C > B，不并行 |
| 对历史代码不熟悉 | 多读测试用例，Git history，问 Owner |
| Phase 1 时间不足 | 缩减 Phase 2 范围，资产时间线可砍 |

---

## 六、时间估算与里程碑

### 总体时间线

```
Phase 0: 环境验证          1 天
Phase 1: V1 Goal 阻塞解除  2-3 周
  ├─ 后端 Final Film      1 周
  ├─ 后端 Worker 异步链   1 周
  └─ 前端 Agent Runtime   1 周
Phase 2: 业务功能补全      2-3 周 (可与 Phase 1 部分并行)
  ├─ 资产时间线(可选)     1 周
  ├─ 约束注入            1 周
  └─ 前端设计修复         1 周
Phase 3: 发布准备          1 周
  ├─ Golden 重跑         3 天
  └─ 文档更新            2 天

总计: 5-7 周
```

### 里程碑

| 里程碑 | 交付物 | 目标日期（从现在起） |
|-------|--------|---------------------|
| **M0**: 环境就绪 | Docker 栈运行、质量门禁通过 | +1 天 |
| **M1**: Final Film 可生成 | 3 个 Shot 合成 MP4 | +1 周 |
| **M2**: Worker 链路闭环 | NodeRun 失败重试、依赖检查 | +2 周 |
| **M3**: 前端状态管理完善 | Agent Runtime + 进度展示 | +3 周 |
| **M4**: 约束注入可用 | 生成时自动注入上游状态 | +4 周 |
| **M5**: V1 Goal DONE | G7/G8 完成，Golden 证据收集 | +5-6 周 |
| **M6**: 准备发布 | 文档齐全，Release Notes 就绪 | +7 周 |

---

## 七、验收标准

### V1 最小可发布标准

**功能完整性**:
- ✅ 从 Template Start 创建项目
- ✅ Director 给出 Story / Scene / Shot 建议
- ✅ 用户可接受/拒绝建议，手动修改
- ✅ 选择 Agnes（图像）+ MiniMax（视频）生成镜头
- ✅ 实时看到 Production Graph 执行进度
- ✅ Shot 失败后可重试
- ✅ 最终导出 MP4 + SRT
- ✅ 整个流程有完整血缘追踪

**技术指标**:
- API P95 响应时间 < 500ms（非生成接口）
- Worker 任务成功率 > 90%（含重试）
- 前端首屏加载 < 3s
- 质量门禁全通过

**文档完整性**:
- README 准确描述功能与限制
- V1 Release Notes 明确已知问题
- Runbook 可指导新开发者搭建环境
- Golden 证据绑定 current commit

### 明确的非目标（V1 不做）

- ❌ 自动人脸一致性检测（Face Embedding）
- ❌ 生成后视觉 LLM 质检
- ❌ 成本追踪与预算守卫
- ❌ 本地 ComfyUI 部署
- ❌ 剪映草稿 / DaVinci XML 导出
- ❌ 多用户协作
- ❌ 复杂的权限管理

---

## 八、后续迭代方向（V2+）

### V1.1 快速迭代（发布后 1-2 月）
- 资产状态时间线（如用户反馈需要）
- 成本追踪仪表盘
- 剪映草稿导出

### V2.0 能力增强（3-6 月）
- 可选 Face Embedding 检测
- 生成后质检 Agent
- 更多模型接入（可灵、即梦）
- 本地 ComfyUI 支持

### V3.0 商业化（6-12 月）
- 多用户协作
- 团队权限管理
- 企业级部署方案
- SaaS 版本

---

## 九、关键决策记录

### 决策 1: 为什么不做 Face Embedding？
**原因**:
- README 明确："首版不集成人脸 embedding、生物特征识别"
- Migration 已删除相关表和字段
- 用户通过"试拍验收"替代自动检测

### 决策 2: 为什么只做 MP4 + SRT？
**原因**:
- 剪映草稿逆向维护成本高
- DaVinci XML 优先级不如跑通主流程
- V1 目标是"可用"而非"完美"

### 决策 3: 为什么资产时间线是"可选"？
**原因**:
- 当前无此表，补全需 1 周
- 如用户实际不需要（手动审核足够），工作量浪费
- 建议先跑通主流程，根据用户反馈决定

### 决策 4: 为什么不重构整个前端？
**原因**:
- 当前前端框架（React + TanStack）选型正确
- 问题是局部设计混乱，非架构性缺陷
- 增量修复比推倒重来风险更低

---

## 十、附录

### A. 关键文件清单

**后端核心**:
```
backend/app/production/service.py       # Production Graph 服务
backend/app/execution/runner.py         # NodeRun 执行器
backend/app/providers/compiler.py       # Provider 请求编译
backend/app/providers/runtime.py        # Provider 执行运行时
backend/app/delivery/final_film.py      # Final Film 合成
backend/app/consistency/constraint_builder.py  # 约束构建器（新增）
```

**前端核心**:
```
frontend/src/contexts/AgentRuntimeContext.tsx  # Agent Runtime（新增）
frontend/src/hooks/useProductionEvents.ts      # SSE 事件流（新增）
frontend/src/components/production/ProductionGraphProgress.tsx  # 进度展示（新增）
frontend/src/components/artifacts/ArtifactPreview.tsx  # 产物预览（新增）
frontend/src/features/director/DirectorSidebar.tsx  # Director 侧边栏
```

**配置与迁移**:
```
backend/alembic/versions/20260907_0056_asset_state_timeline.py  # 时间线表（可选）
backend/alembic/versions/20260907_0057_continuity_constraints.py  # 约束表（可选）
```

### B. 命令速查

```powershell
# 启动开发环境
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 运行质量门禁
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1

# 查看 Task 日志
.\.agent-control\control.ps1 -Operation tail -Tail 20

# 数据库迁移
docker compose exec api alembic upgrade head

# 前端开发
cd frontend && npm run dev
```

### C. 术语对照

| 术语 | 定义 |
|-----|------|
| Production Graph | 生产图谱，DAG 结构，每个 Node 是一个加工步骤 |
| NodeRun | 节点执行记录，带状态、checkpoint、重试 |
| Provider | 模型供应商（Agnes / MiniMax / Volcengine） |
| Compiler | 将导演意图编译为模型原生请求 |
| EffectiveRequest | 实际发送给模型的完整请求快照 |
| Artifact | 生产产物（图像、视频、音频） |
| Canvas | 画布，当前制作事实的可视化 |
| Director | 导演智能体，AI 辅助创作 |
| Proposal | AI 提案，可接受/拒绝 |
| Golden | 发布前的完整功能验证证据 |

---

**文档维护**: 本方案基于 2026-09-07 状态，应随实施进展更新。
