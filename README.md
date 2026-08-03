# DramaForge

DramaForge 是面向个人创作者私有化部署的镜头级 AI 短剧生产工作台。项目以受控 Production Graph 管理剧本、资产、生成、连续性检查、审核、成本、局部返工和可追溯交付。

## 当前状态

仓库当前处于 **P0 功能候选版**，已经具备账号与私有创作空间、同一 Project 的快速/专业双入口、受控 Brief/Plan、10 Shot Production Graph、ProviderOperation/Artifact 血缘、审核、局部返工、导出、RLS、Outbox/SSE 和 Docker Compose 正式运行栈。当前候选仍未关闭 Graph 依赖顺序、人脸一致性真实 Gate 和当前提交上的完整 10 Shot 交付证据，因此不得标记 P0 MVP 完成。证据化现状、优缺点和需求冲突见 [`docs/项目现状与需求对齐-20260801.md`](docs/项目现状与需求对齐-20260801.md)。

**状态语义：** 本地质量入口（`scripts/run_quality.ps1`，使用 `backend/.venv`）通过，**不等于** P0 MVP 已完成。Docker Compose 的 PostgreSQL、Redis、MinIO、API、dispatcher 与 Arq Worker 已完成本机启动验证；真实 Provider 与完整交付必须按候选提交重新形成正式证据。下一步工程主线和剩余 Gate 见 `docs/开发执行检查点.md`。

S0-A 已使用本地 InsightFace 1.0.1 / ONNX Runtime CPU 对 20 对同角色、20 对异角色和 10 个异常样本完成 FAR/FRR 校准，并有带审批标识的最终阈值；见 [`docs/spikes/s0a-face-consistency.md`](docs/spikes/s0a-face-consistency.md)。当前唯一执行任务、外部暂停项和后续 `READY` 队列以 [`docs/开发执行检查点.md`](docs/开发执行检查点.md) 为准。

P0 完成标准是使用一份 3-5 场、至少 10 Shot、至少 1 名主角的冻结样本，完成从正式 Project、Brief/Plan、资产和参考，到图像、视频、语音、字幕、合成、审核和 `MP4 + SRT + 素材包 + timeline_json` 的可追溯交付。

## 开发目录

唯一代码仓和 Git 根目录：

```text
D:\dramaforge
```

`D:\项目` 保存外部研究和源资料，不是开发工作区。任何应用代码、迁移、测试、fixture 或运行手册都不得写入研究目录。

## 本地启动

### 架构总览

无论用哪种方式，最终都需要以下组件：

| 组件 | 说明 |
|------|------|
| PostgreSQL 15 | 主数据库 |
| Redis 7 | 任务队列（Arq） |
| MinIO | S3 兼容对象存储 |
| API (FastAPI) | `:8000`，后端服务 |
| Dispatcher / Worker (default + heavy) | Outbox 派发与 Arq 异步任务消费 |
| 前端 (Vite + React) | `:5173`，浏览器打开 |

`docker-compose.yml` 是唯一的服务端部署方式：它启动 PostgreSQL、Redis、MinIO、迁移、API、常驻 Outbox dispatcher 与两类 Arq Worker。前端使用本机 Vite 提供 HMR；它通过 `http://127.0.0.1:8000` 访问 Compose API。

---

### Docker Compose

把所有后端服务跑在 Docker 容器内，网络在容器内网打通，最稳定。

**前置条件**：Docker Compose v2。

**1. 准备环境文件**

```powershell
Copy-Item .env.example .env
```

`.env.example` 是假值，本地开发可以直接用；如果需要非假密钥：

```powershell
# SESSION_SECRET
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })

# BYOK_FERNET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**2. 启动后端容器**

```powershell
docker compose up -d
```

Compose 会从本地忽略的 `.env` 读取 `AGNES_*`、`TEXT_LLM_*` 和可选的 `TTS_*`，
并仅注入 API 与 Worker 容器；未配置时保持 fail-closed。不要把真实密钥写入
`docker-compose.yml` 或提交到 Git。

> 这会启动 **所有** 服务（postgres、redis、minio、migrate、api、dispatcher、worker-default、worker-heavy）。首次运行会构建 `backend/Dockerfile` 镜像，其中包含 FFmpeg、eSpeak NG、InsightFace 0.7.3、ONNX Runtime CPU 与预下载的 buffalo_l 模型。构建会执行 `FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"]).prepare(ctx_id=-1)`；初始化失败时不会生成服务镜像。

**3. 启动前端**

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

浏览器打开 `http://localhost:5173`。

**4. 验证**

```powershell
curl http://localhost:8000/health
# → {"status":"ok","db":"up"}
```

验证镜像内的人脸一致性运行时，不依赖宿主机 Python 或模型下载：

```powershell
docker compose build api worker-heavy
docker run --rm --entrypoint python dramaforge-api:latest -c "import json; from app.consistency.image_embed import insightface_status; print(json.dumps(insightface_status(), sort_keys=True))"
# → {"available": true, "backend": "insightface+onnx", "embedding_dim": 512, "error": null}
```

`insightface_status()` 的 `available=true` 只证明镜像内的 CPU 初始化与 512 维 embedding 运行时可用；它不替代 S0-A 的 FAR/FRR 校准，也不关闭 P0 的正式证据 Gate。

**GPU / ComfyUI（可选）**：

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up -d
```

---

### 原生 Python 调试

当你需要在宿主机打断点调试 Python 代码时。

先启动 Docker 基础设施：`docker compose up -d postgres redis minio`。原生调试不提供另一套部署模式；数据库、队列和对象存储仍由 Compose 管理。

**后端**（Python 3.12 + venv）：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

**Worker**（需 Redis 已启动）：

```powershell
python -m app.workers.main default
arq app.workers.default.WorkerSettings

python -m app.workers.main heavy
arq app.workers.heavy.WorkerSettings
```

**前端**（同上）：

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

> 工作台壳使用 TanStack Router + QueryClient；服务端状态只放 TanStack Query，Zustand 仅保存布局/选择等 UI 状态。

## 测试与质量门禁

一键（需已安装后端 venv 依赖与前端 `node_modules`）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality.ps1
```

分项：

```powershell
# 目录合规（拒绝未登记根目录与敏感/构建产物）
python .\scripts\check_directory_compliance.py

# 后端
cd backend
python -m ruff check app tests
python -m mypy app
python -m pytest -q

# 前端
cd frontend
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run test
npm.cmd run build

# OpenAPI → TypeScript（可重复生成，二次运行应无有意义 diff）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\generate_openapi_types.ps1
```

演示目录检查的拒绝路径：

```powershell
python .\scripts\check_directory_compliance.py --demo-unregistered utils2 --demo-sensitive .env
```

## 开始开发（Agent）

编码 Agent 必须先读取：

1. [`agent.md`](agent.md)
2. [`AGENT_EXECUTION_PROTOCOL.md`](AGENT_EXECUTION_PROTOCOL.md)
3. 本机 `.agent-control/PROGRESS.jsonl` 尾部和 `open` 结果
4. [`docs/开发执行检查点.md`](docs/开发执行检查点.md)
5. 当前 Task 明确引用的 [`01_项目总需求.md`](01_项目总需求.md) 至 [`06_受控混合Agent运行时规范.md`](06_受控混合Agent运行时规范.md) 条款

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation open
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation tail -Tail 20
git status --short
git worktree list
git branch --all
git remote -v
```

每个任务开始、完成、失败或暂停时，通过 `.agent-control/control.ps1 -Operation log` 追加事实记录。日常开发在根 worktree 的本地 `dev` 分支进行，提交后推送到 `origin/dev`；推送前本地 `dev` 可以领先远端。`main` 只保留经过验证的稳定版本，并且只能通过 `dev -> main` 的受保护 PR 更新。需要并行隔离或紧急修复时，才从当前本地 `dev`（紧急修复从 `main`）创建短期 `agent/<task-id>` 分支和 `.worktrees/<task-id>`，其 PR 先合回 `dev`（紧急修复合回 `main` 后也要同步回 `dev`）。Agent 不得批准、合并或记录 `MERGED`；只有 `@zwb2002-yjy` 可以在批准并合并 PR 后记录该状态。GitHub Ruleset 配置见 [`docs/runbooks/github-ruleset.md`](docs/runbooks/github-ruleset.md)。

发布或 P0 tag 前，从候选 commit 的干净 worktree 运行 formal proof 和 §3.1 Gate。默认报告写入 `tmp/p0-evidence/<sha>/`，并携带 commit、dirty、UTC 起止时间、脱敏命令、环境摘要和 source 一致性；任何 `FAIL`、`BLOCKED`、dirty 或 source mismatch 都不能标记 P0 MVP 完成。

Agent 不以完成一个 Task 作为停机条件。每个 Task 开始前先在开发检查点定义可观察效果和验收证据；完成并合并后重算当前阶段 Gate，继续最高优先级的 `READY` Task。某个外部条件暂停时，只暂停依赖它的路径；P0 完成后按 `P1.1 -> P1.2 -> P1.3 -> P2` 自动建立阶段合同并继续开发，除非遇到需要用户账号、付费、受限数据、不可逆操作或会改变产品路线的真实阻塞。

## 产品阶段

- P0：内部试产的完整 MVP。
- P1.1：候选结果治理。
- P1.2：团队评论、指派和责任闭环。
- P1.3：富故事板、受控精剪和条件性 OpenCut 适配。
- P2：3D 导演台和高级专业后期互操作。

详细效果和进入条件见 [`docs/产品阶段与效果路线图.md`](docs/产品阶段与效果路线图.md) 与 [`docs/MVP能力延期台账.md`](docs/MVP能力延期台账.md)。
