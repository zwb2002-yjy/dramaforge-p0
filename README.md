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
| API (FastAPI) | Compose 内网 `:8000`，后端服务 |
| Dispatcher / Worker (default + heavy) | Outbox 派发与 Arq 异步任务消费 |
| 前端网关 (React + Nginx) | 默认唯一入口 `127.0.0.1:8080` |

`docker-compose.yml` 是完整发布拓扑：它构建前端静态产物与非特权 Nginx 网关，并启动
PostgreSQL、Redis、MinIO、LiteLLM、迁移、API、常驻 Outbox dispatcher 与两类 Arq Worker。
只有前端网关发布宿主端口，其他服务保留在 Compose 内网。

---

### Docker Compose

把完整应用跑在 Docker 容器内，网络在容器内网打通。

**前置条件**：Docker Compose v2。

**1. 准备环境文件**

```powershell
python scripts/init_env.py
```

该命令从 `.env.example` 创建本地 `.env`，为 Session、Worker、BYOK Fernet 和
LiteLLM 分别生成唯一密钥，且不会把密钥值打印到终端。为避免误覆盖，`.env` 已存在时命令会
直接拒绝；需要保留的 Provider BYOK 应继续只写入本地 `.env`。Compose 对这些必需密钥
采用 fail-fast 校验，空值或缺失时不会启动。

默认部署为单用户模式（`PUBLIC_REGISTRATION_ENABLED=false`）：干净数据库允许在登录页创建
第一个 Owner；创建成功后后端 `/api/v1/auth/register` 返回 `REGISTRATION_CLOSED`，前端也会
隐藏初始化入口。不要为了“修复登录”删除数据库。只有明确需要多账号实验时，才在受控环境将
该变量改为 `true`。

> 如果旧 `.env` 来自早期版本，请先备份并手工补齐
> `POSTGRES_PASSWORD`、`MINIO_ROOT_PASSWORD`、`LITELLM_DB_PASSWORD`、`SESSION_SECRET`、
> `WORKER_TOKEN`、`BYOK_FERNET_KEY`、`LITELLM_MASTER_KEY`；不要用仓库
> 文档里的公共固定值。已经加密保存 BYOK 后不得随意替换 Fernet key，应按密钥轮换工具操作。

**2. 启动完整应用**

```powershell
docker compose up -d --build
```

Compose 会从本地忽略的 `.env` 读取 `AGNES_*`、`TEXT_LLM_*` 和可选的 `TTS_*`，
并仅注入 API 与 Worker 容器；未配置时保持 fail-closed。不要把真实密钥写入
`docker-compose.yml` 或提交到 Git。

> 这会启动 **所有** 服务（postgres、redis、minio、litellm、migrate、api、frontend、dispatcher、worker-default、worker-heavy）。首次运行会构建前后端镜像。后端包含 FFmpeg、eSpeak NG 和可选的 InsightFace Python 运行时代码，但不包含、下载或初始化任何 InsightFace 预训练权重。

**3. 验证**

```powershell
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health
# → {"status":"ok","db":"up"}
```

浏览器打开 `http://localhost:8080`。默认只绑定回环地址，不提供 TLS；公网或局域网部署必须
明确配置入口与 HTTPS 边界，详见
[`docs/runbooks/docker-deployment.md`](docs/runbooks/docker-deployment.md)。

默认镜像应明确报告 InsightFace 未启用：

```powershell
docker compose exec api python -c "import json; from app.consistency.image_embed import insightface_status; print(json.dumps(insightface_status(), sort_keys=True))"
# → {"available": false, "backend": "hash_placeholder", ...}
```

DramaForge 不分发或自动下载 `buffalo_l`。只有在部署者自行确认模型文件的来源、许可和用途，
把模型目录只读挂载到容器，并设置 `INSIGHTFACE_ENABLED=true`、
`INSIGHTFACE_MODEL_ROOT=/models/insightface` 后才会尝试加载。预期目录结构为
`/models/insightface/models/<INSIGHTFACE_MODEL_NAME>/*.onnx`；缺少文件时保持 fail-closed，
不会触发库的隐式联网下载。即使 `available=true`，它也只证明人脸 embedding 运行时可用，
不等于人物一致性已解决，也不能单独作为发布 Gate。

**GPU / ComfyUI（可选）**：

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up -d
```

---

### 原生 Python 调试

当你需要在宿主机打断点调试 Python 代码时。

先用开发 override 启动 Docker 基础设施：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis minio
```

`docker-compose.dev.yml` 会显式开放调试端口，不得用于不受信网络。原生调试不提供另一套部署
模式；数据库、队列和对象存储仍由 Compose 管理。

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

## 开源治理

DramaForge 以 [Apache License 2.0](LICENSE) 开源。提交代码前请阅读
[贡献指南](CONTRIBUTING.md)、[安全策略](SECURITY.md)、
[社区行为准则](CODE_OF_CONDUCT.md) 与 [第三方声明](THIRD_PARTY_NOTICES.md)。

仓库提供 AIOS/AISphere 的 Compose 交接描述，但尚未在真实 AIOS 环境验证，也没有冒充平台
官方 manifest；边界与集成验收见
[`docs/runbooks/docker-deployment.md`](docs/runbooks/docker-deployment.md)。
