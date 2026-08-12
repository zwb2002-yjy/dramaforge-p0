# DramaForge

DramaForge 是面向零基础个人创作者的开源 AI 导演工作台。首版聚焦从一个想法完成一部
15–30 秒、真人写实风格、角色对白驱动的多镜头短剧：生成前确认创作与拍摄方案，用代表
镜头试拍降低盲抽成本，失败后提供有证据和成本范围的局部修复，并保留完整产物血缘。

## 当前状态

仓库当前处于 **产品架构重置期**。旧 P0 已有 Production Graph、异步任务、Provider 插件、
Artifact 血缘、审核、局部返工和交付等可复用底座，但快速流程、固定 10 Shot 和单一人脸
阈值不代表新产品已经完成。2026-08-12 起按首版 AI 导演体验重构；在同一发布提交通过真实
作品、三名目标用户、质量校准和跨平台部署 Gate 前，不得标记核心体验稳定。

**状态语义：** 历史测试或专题实现通过，**不等于** 新版产品或用户价值已完成。唯一产品总纲见
[`DramaForge总开发文档.md`](DramaForge总开发文档.md)，文档职责与阅读顺序见
[`docs/README.md`](docs/README.md)，当前执行合同见 [`docs/current/`](docs/current/)，实时工程状态见
[`docs/开发执行检查点.md`](docs/开发执行检查点.md)。

历史 S0-A 使用本地 InsightFace / ONNX Runtime 得到过 `0.60` 实验阈值；这只证明人脸信号可运行，
不等于人物一致性已解决，也不再是发布级唯一 Gate。新质量体系要求先验证参考资产进入有效请求，
再以多信号、真实校准集和人工验收判断。历史原始结果见
[`docs/spikes/s0a-face-consistency.md`](docs/spikes/s0a-face-consistency.md)。

2026-09-15 首版发布标准见 [`docs/current/01-产品与发布契约.md`](docs/current/01-产品与发布契约.md)；
不再以固定 10 Shot 作为产品完成条件。

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

Agent 不以完成一个 Task 作为停机条件。每个 Task 开始前先在开发检查点定义可观察效果和验收证据；完成并合并后重算当前阶段 Gate，继续最高优先级的 `READY` Task。某个外部条件暂停时，只暂停依赖它的路径；P0 完成后按个人创作者路线 `P1.1 -> P1.2 -> P1.3 -> P2` 建立阶段合同，除非遇到需要用户账号、付费、受限数据、不可逆操作或会改变产品路线的真实阻塞。

## 产品阶段

- P0：内部试产的完整 MVP。
- P1.1：个人候选结果治理、选片与项目内复用。
- P1.2：个人故事板、审核/返工队列、正式资产库与模板复用。
- P1.3：版本化时间线、受控精剪和条件性后期工具适配。
- P2：3D 导演台和高级专业后期互操作。

成员、邀请、共享、评论和任务指派不在当前个人创作者路线中。

详细效果和进入条件见 [`docs/产品阶段与效果路线图.md`](docs/产品阶段与效果路线图.md) 与 [`docs/MVP能力延期台账.md`](docs/MVP能力延期台账.md)。
