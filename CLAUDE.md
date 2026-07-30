# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

DramaForge 是面向个人创作者的镜头级 AI 短剧生产工作台，私有化部署。一个账号可拥有多个私有创作空间（Workspace），每个空间包含独立的项目、素材、预算和凭证。以受控 Production Graph 管理剧本、资产、生成、连续性检查、审核、成本和可追溯交付。

P0 目标为可运行的 React/FastAPI/PostgreSQL/Redis/MinIO/Arq 应用 + 一份 3–5 场、至少 10 Shot、至少 1 名主角的冻结黄金样本，产出可重现的 MP4、SRT、素材包和 timeline JSON 交付。

当前 `dev` 分支已从团队协作模型重构为个人创作空间模型（`docs/个人创作空间重构方案.md`），移除了 Organization、成员、角色等概念。`main` 分支仍保留重构前的团队向代码。

### 当前完成度

**标签：P0 功能候选版**（2026-07-23 标记）

已实现：
- 应用骨架：FastAPI `/health`、Arq default/heavy Worker、React 工作台壳、Docker Compose 全栈
- 个人创作空间模型：User → Workspace → Project，RLS 隔离，BYOK 凭证管理
- Production Graph 完整链路：Brief/Plan → GraphVersion → NodeRun → ProviderOperation → Artifact → 审核 → 导出
- 手工媒体路径：10 Shot 全必需节点、approve_ok=10、failed=0、package.zip 哈希一致、真实 MP4
- FFmpeg 导出、缓存复用、幂等取消/补偿、Outbox/SSE/Redis Streams 事件流
- 目录合规、Ruff/mypy/unit/integration/frontend/e2e CI 门禁全绿
- Compose 镜像内 InsightFace 0.7.3 / ONNX Runtime CPU / buffalo_l 已完成构建期 `FaceAnalysis.prepare()` 与容器运行期 512-d smoke

P0 Gate 阻塞项（19 PASS / 4 BLOCKED）：
1. 未配置真实文本 LLM BYOK，无法现场证明 Agent Brief→Plan→10 Shot 全链
2. 需将已有 InsightFace 20/20/10 FAR/FRR 校准与当前候选提交的正式证据链重新绑定
3. 缺少真实 review_passed Shot 和逐 Shot 审核/驳回/重跑闭环
4. 备份恢复、密钥轮换、真实 Playwright 10 Shot E2E 未留存

## 技术栈（不可替换）

- **后端**：Python 3.12, FastAPI 0.115.x, Pydantic v2, SQLAlchemy 2.0 async (`Mapped`/`mapped_column`/`AsyncSession`), asyncpg, Alembic 1.14+
- **任务队列**：Arq 0.26+ (唯一，`default` 做 I/O、`heavy` 做媒体/推理), Redis 7+ 作队列，Transactional Outbox 派发，禁止业务 Module 直调 `arq.enqueue_job()`
- **实时事件**：Redis Streams（关键状态）+ SSE（客户端），支持 `Last-Event-ID` 续传
- **存储**：MinIO（S3 兼容），数据库只存 object key/哈希/元数据
- **前端**：React 18, TypeScript, Vite, TanStack Router/Query, Zustand（仅 UI 状态）, Tailwind, shadcn/Radix
- **人脸一致性**：InsightFace 0.7+ + ONNX Runtime CPU, 512 维归一化向量
- **图像生成**：Flux, Kling; **媒体处理**：FFmpeg 6+; **TTS**：Azure TTS
- **本地设施**：PostgreSQL 15, Redis 7, MinIO; Docker Compose 容器化除前端外所有组件

详细锁定见 `02_全栈技术栈锁定表.md`。

## 产品模型（dev 分支）

```text
账号
  → 创作空间（Workspace，owner_user_id）
    → 项目（Project，workspace_id）
      → 剧本、角色、素材、分镜、生成任务、导出结果
```

空间之间完全隔离，不可共享、转让或邀请成员。注册后自动创建默认空间。所有写入/审核/导出/凭证操作统一校验当前用户是否为 `owner_user_id`。

已移除的概念：Organization、OrganizationMember、ProjectMember、MemberRole、成员邀请。`main` 分支仍保留团队协作模型。

## 后端目录架构（不可新建/移动/合并）

后端分层：Route → Service → Repository/Domain。禁止 Route 直接写 SQL，禁止业务 Service 直调 Provider/Redis/FFmpeg。

```
backend/app/
  api/deps.py, errors.py, v1/         # FastAPI 路由（按领域拆分）
  access/    # User/Workspace/项目权限、RLS
  creation/  # Brief/Plan 创建体验、Agent 运行时、物化
  assets/    # 剧本导入、角色/场景/道具、参考图
  execution/ # Production Graph、NodeRun、Pipeline、多 Shot
  production/ # Graph 发布、版本管理
  consistency/ # 角色人脸/剧情连续性检查
  providers/   # Flux/Kling/OpenAI/Agnes/TTS Adapter、fake 测试桩
  events/    # Outbox、SSE、Redis Streams
  delivery/  # 导出（MP4/SRT/timeline JSON/素材包）
  storage/   # MinIO 对象存储封装
  security/  # BYOK 密钥管理、credential 加密
  shared/    # Base, db, enums, errors, ids, json, security, observability
  runtime/   # AgentRunScheduler, Redis dispatch
  workers/   # Arq default/heavy Worker 入口
frontend/src/
  routes/       # TanStack Router 路由
  features/     # 按领域：projects/creation/assets/storyboard/production/review/delivery/audit
  components/   # ui/（基础）, workstation/（布局）, shared/（跨feature展示）, sse/
  hooks/        # useSSE.ts
  lib/          # api.ts（唯一REST客户端）, queryKeys.ts
  stores/       # uiStore.ts（仅UI偏好，不放服务端数据）
  types/        # api.ts（OpenAPI自动生成，禁止手动编辑）, view.ts
```

`03_全局目录规范.md` 是所有模块边界的权威来源。禁止新建 `common`/`helpers`/`misc`/`utils2` 等目录。

## 开发命令

```powershell
# 本地开发栈（Docker Compose 推荐）
docker compose up -d                          # 启动全部后端
cd frontend && npm.cmd install && npm.cmd run dev  # 启动前端 (:5173)
curl http://localhost:8000/health

# 质量一键
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality.ps1

# 后端分项
cd backend
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest tests/unit -q
.\.venv\Scripts\python.exe -m pytest tests/integration -q -rs --fail-on-skip
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head

# 前端分项
cd frontend
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run test
npm.cmd run build
npm.cmd run test:e2e -- tests/e2e/smoke.spec.ts

# 单个测试
cd backend && .\.venv\Scripts\python.exe -m pytest tests/unit/test_workspace_byok.py -q
cd backend && .\.venv\Scripts\python.exe -m pytest tests/unit/test_workspace_byok.py::test_workspace_byok_api_stores_without_readback -q
```

## Git 工作流（强制执行）

- 日常开发在 `dev` 分支，推送到 `origin/dev`
- **禁止直接推送 `main`**（pre-push hook 会拒绝）
- 只读 subagent 可并行；并行写入 subagent 必须使用独立 `agent/<task-id>` 分支 + `.worktrees/<task-id>` + 不重叠的 `owned_paths`
- 稳定发布通过 `dev -> main` PR；紧急 hotfix 用 `agent/hotfix-*` 从 `main` 分支并合回 `main` 后同步到 `dev`
- Agent 可以提交/推送/创建 PR/复核 diff，**不得批准、合并或记录 `MERGED`**——只有 `@zwb2002-yjy` 能执行这些动作
- 禁止 force push、历史重写、未审查自动合并、`git reset --hard`

## CI 门禁

PR 合并到 `dev` 或 `main` 前必须通过 7 个 job（`.github/workflows/ci.yml`）：
`policy` → `backend-static`（ruff + mypy）→ `backend-unit` → `postgres-integration`（真实 PG，不可 SQLite）→ `frontend` → `frontend-smoke` → `frontend-smoke-windows`

## Agent 执行约定

- 从 `docs/开发执行检查点.md` 的"当前唯一执行任务"恢复
- 写 Task 合同后再写 `STARTED`；完成/失败/暂停后立即通过 `.agent-control/control.ps1 -Operation log` 记录
- `COMPLETED` = 含测试证据的完成效果；`PAUSED` = 外部阻塞 + 准确继续条件；`FAILED` = 当前方案已被证据否定
- 失败后按诊断→根因修复→回归循环自主处理，不把可复现问题直接转人工
- 冻结包（`01`–`06`）+ ADR 发生冲突时，先引用条款、记录检查点、停止冲突范围实现，其余工作继续
- 本地编码/测试/迁移/依赖冲突/分支冲突/文档同步不属于人工审批事项

P0 不开发：候选结果池（P1.1）、评论指派（P1.2）、富故事板/精剪/FCPXML（P1.3）、3D导演台（P2）、通用 NLE、插件市场、WebSocket、Adobe Premiere 兼容
