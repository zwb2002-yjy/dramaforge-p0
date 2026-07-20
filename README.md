# DramaForge

DramaForge 是面向 1-6 人短剧制作团队私有化部署的镜头级 AI 生产工作台。项目以受控 Production Graph 管理剧本、资产、生成、连续性检查、审核、成本、局部返工和可追溯交付。

## 当前状态

仓库已完成 `BOOT-0` 可运行骨架：FastAPI `/health`、Arq default/heavy Worker 入口、React 工作台壳、Docker Compose（PostgreSQL / Redis / MinIO / API / Workers）、质量门禁与目录合规检查。业务运行时（会话、RLS、Graph 执行、Provider）从 S1 起按 Gate 落地。

P0 完成标准是使用一份 3-5 场、至少 10 Shot、至少 1 名主角的冻结样本，完成从正式 Project、Brief/Plan、资产和参考，到图像、视频、语音、字幕、合成、审核和 `MP4 + SRT + 素材包 + timeline_json` 的可追溯交付。

## 开发目录

唯一代码仓和 Git 根目录：

```text
D:\调研\dramaforge
```

`D:\调研\项目` 保存外部研究和源资料，不是开发工作区。任何应用代码、迁移、测试、fixture 或运行手册都不得写入研究目录。

## 本地启动

### 1. 环境文件

```powershell
Copy-Item .env.example .env
```

`.env.example` 仅含假值。生产或共享环境请重新生成：

```powershell
# SESSION_SECRET
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })

# BYOK_FERNET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. 基础设施 + API + Workers（Docker Compose）

需要本机已安装 Docker Compose v2：

```powershell
docker compose config
docker compose up -d postgres redis minio
docker compose up -d api worker-default worker-heavy
curl http://localhost:8000/health
```

GPU / ComfyUI **默认不启用**。仅在有明确需求时：

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up -d
```

### 3. 后端（本地 Python 3.12）

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Worker 入口（需 Redis）：

```powershell
python -m app.workers.main default
arq app.workers.default.WorkerSettings
python -m app.workers.main heavy
arq app.workers.heavy.WorkerSettings
```

### 4. 前端（Node 20+）

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

浏览器打开 `http://localhost:5173`。工作台壳使用 TanStack Router + QueryClient；服务端状态后续只放 TanStack Query，Zustand 仅保存布局/选择等 UI 状态。

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
```

每个任务开始、完成、失败、暂停或合并时，通过 `.agent-control/control.ps1 -Operation log` 追加事实记录。写入 subagent 在基线提交后使用独立 `agent/<task-id>` 分支与 `.worktrees/<task-id>`。

## 产品阶段

- P0：内部试产的完整 MVP。
- P1.1：候选结果治理。
- P1.2：团队评论、指派和责任闭环。
- P1.3：富故事板、受控精剪和条件性 OpenCut 适配。
- P2：3D 导演台和高级专业后期互操作。

详细效果和进入条件见 [`docs/产品阶段与效果路线图.md`](docs/产品阶段与效果路线图.md) 与 [`docs/MVP能力延期台账.md`](docs/MVP能力延期台账.md)。
