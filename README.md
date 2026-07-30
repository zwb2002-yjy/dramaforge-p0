# DramaForge

DramaForge 是面向 1-6 人短剧制作团队私有化部署的镜头级 AI 生产工作台。项目以受控 Production Graph 管理剧本、资产、生成、连续性检查、审核、成本、局部返工和可追溯交付。

## 当前状态

仓库已经实现 `BOOT-0` 应用骨架：FastAPI `/health`、Arq default/heavy Worker 入口、React 工作台壳、Docker Compose（PostgreSQL / Redis / MinIO / API / Workers）、质量入口与目录合规检查均已落地。

**状态语义：** 本地质量入口（`scripts/run_quality.ps1`，使用 `backend/.venv`）与 Playwright E2E 可在本机跑通，**不等于** BOOT-0 阶段 Gate 全部关闭——容器健康仍依赖 Docker CLI（当前环境可能缺失）。S0-A 数据 Gate 因样本不足为 `BLOCKED_BY_FIXTURE`。下一步工程主线见 `docs/开发执行检查点.md`（S1 切片）。

S0-A 的视觉一致性入口、纯函数和样本采集规范已经提交，但真实 InsightFace/FAR/FRR Gate 因缺少合法样本处于 `BLOCKED_BY_FIXTURE`。当前唯一执行任务、外部暂停项和后续 `READY` 队列以 [`docs/开发执行检查点.md`](docs/开发执行检查点.md) 为准。

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
| Worker (default + heavy) | Arq 异步任务消费 |
| 前端 (Vite + React) | `:5173`，浏览器打开 |

`docker-compose.yml` 已容器化了除前端外的所有组件。**前端目前不容器化**——开发时需要 Vite HMR（热模块替换），始终保持 `npm run dev` 在宿主机运行。

下面提供三种部署方式，**任选其一**：

---

### 方式一：Docker Compose（推荐）

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

> 这会启动 **所有** 服务（postgres、redis、minio、migrate、api、worker-default、worker-heavy）。首次运行会构建 `backend/Dockerfile` 镜像。

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

**GPU / ComfyUI（可选）**：

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up -d
```

---

### 方式二：WSL 一键脚本（Windows 开发推荐）

当 Docker 不可用，且 PostgreSQL 在 WSL 内时使用。脚本自动管理 API 和前端进程。

**为什么需要这个**：如果把 API 放 Windows 但 PG 放 WSL，`127.0.0.1:5432` 的跨边界转发会间歇断开，`/health` 返回 `db=down`。此脚本把 API 也放在 WSL 内，避免这个问题。

```powershell
# 启动
powershell -ExecutionPolicy Bypass -File .\scripts\start_p0_stack.ps1

# 检查状态
powershell -ExecutionPolicy Bypass -File .\scripts\start_p0_stack.ps1 -Action Status

# 停止
powershell -ExecutionPolicy Bypass -File .\scripts\start_p0_stack.ps1 -Action Stop
```

> Windows API 模式：`-Mode WindowsApi -DbHost WslIp`（API 在 Windows，PG 通过 WSL 网卡 IP 直连，不用 localhost 转发）。

详细说明见 [`docs/runbooks/local-stack-bypass.md`](docs/runbooks/local-stack-bypass.md)。

---

### 方式三：后端裸机运行（调试用）

当你需要在宿主机打断点调试 Python 代码时。

**先启动基础设施**（任选其一）：
- Docker：`docker compose up -d postgres redis minio`
- 或宿主机自行安装 PostgreSQL 15+ / Redis 7+ / MinIO，然后修改 `.env` 中的连接地址

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

每个任务开始、完成、失败或暂停时，通过 `.agent-control/control.ps1 -Operation log` 追加事实记录。日常开发在根 worktree 的 `dev` 分支进行，提交后推送到 `origin/dev`；`main` 只保留经过验证的稳定版本，并且只能通过 `dev -> main` 的受保护 PR 更新。需要并行隔离或紧急修复时，才从同步后的 `dev`（紧急修复从 `main`）创建短期 `agent/<task-id>` 分支和 `.worktrees/<task-id>`，其 PR 先合回 `dev`（紧急修复合回 `main` 后也要同步回 `dev`）。Agent 不得批准、合并或记录 `MERGED`；只有 `@zwb2002-yjy` 可以在批准并合并 PR 后记录该状态。GitHub Ruleset 配置见 [`docs/runbooks/github-ruleset.md`](docs/runbooks/github-ruleset.md)。

发布或 P0 tag 前，从候选 commit 的干净 worktree 运行 formal proof 和 §3.1 Gate。默认报告写入 `tmp/p0-evidence/<sha>/`，并携带 commit、dirty、UTC 起止时间、脱敏命令、环境摘要和 source 一致性；任何 `FAIL`、`BLOCKED`、dirty 或 source mismatch 都不能标记 P0 MVP 完成。

Agent 不以完成一个 Task 作为停机条件。每个 Task 开始前先在开发检查点定义可观察效果和验收证据；完成并合并后重算当前阶段 Gate，继续最高优先级的 `READY` Task。某个外部条件暂停时，只暂停依赖它的路径；P0 完成后按 `P1.1 -> P1.2 -> P1.3 -> P2` 自动建立阶段合同并继续开发，除非遇到需要用户账号、付费、受限数据、不可逆操作或会改变产品路线的真实阻塞。

## 产品阶段

- P0：内部试产的完整 MVP。
- P1.1：候选结果治理。
- P1.2：团队评论、指派和责任闭环。
- P1.3：富故事板、受控精剪和条件性 OpenCut 适配。
- P2：3D 导演台和高级专业后期互操作。

详细效果和进入条件见 [`docs/产品阶段与效果路线图.md`](docs/产品阶段与效果路线图.md) 与 [`docs/MVP能力延期台账.md`](docs/MVP能力延期台账.md)。
