# DramaForge

DramaForge 是面向专业个人创作者的开源 AI 影视制作工作台。首版聚焦围绕场景、镜头和资产完成一部
15–30 秒、真人写实风格、角色对白驱动的多镜头短剧：生成前确认创作与拍摄方案，用代表
镜头试拍降低盲抽成本，失败后提供有证据和成本范围的局部修复，并保留完整产物血缘。

## 当前状态

当前开发按项目 Owner 于 **2026-08-26** 指定并已内化的 Professional 七方案执行。产品、技术、模型供应与阶段顺序的唯一入口是：

- [`DramaForge总开发文档.md`](DramaForge总开发文档.md)；
- [`docs/plans/professional-program-v2/README.md`](docs/plans/professional-program-v2/README.md)。

代码、迁移、测试和运行证据说明“现在实际是什么”；七方案与其 Review 修订决定“接下来必须成为什么”。任何历史 P0、旧总纲、旧 `docs/current/` 合同或旧 Release Board 的通过记录都不能替代当前七方案 Task 的完成证据。

首版不集成人脸 embedding、生物特征识别或相似度阈值。人物一致性先验证角色参考真实进入有效请求，再保存生成产物与视频首/中/末帧证据，由用户在试拍中验收；没有可信且校准过的自动评估器时，系统返回 `needs_human`，不会伪造通过分数。

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
| Web/API gateway | `http://localhost:8080` |
| Dispatcher / Worker (default + heavy) | Outbox 派发与 Arq 异步任务消费 |
| 前端网关 (React + Nginx) | 默认唯一入口 `127.0.0.1:8080` |

`docker-compose.yml` 是完整发布拓扑：它只使用版本化成品镜像，启动 PostgreSQL、Redis、
MinIO、LiteLLM、迁移、API、常驻 Outbox dispatcher、两类 Arq Worker 与非特权 Nginx 网关。
只有前端网关发布宿主端口，其他服务保留在 Compose 内网。普通用户无需安装 Python、Node.js
或编译器，也不会在安装时执行 `apt`、`pip`、`npm` 或源码构建。

---

### Docker Compose

把完整应用跑在 Docker 容器内，网络在容器内网打通。

**前置条件**：Docker Compose v2。

**在线安装（普通用户）**

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Linux/macOS：

```sh
chmod +x install.sh
./install.sh
```

请从同一 GitHub Release 解压完整在线安装包后运行脚本。安装器读取发布包中的
`release.env`，拉取与发布 commit 绑定的不可变镜像，在后端成品镜像内生成本地 `.env`，
然后执行 Compose 健康等待；宿主机只需要 Docker Compose v2。已有 `.env` 升级时会保留
数据库密码、Fernet 密钥和 Provider 配置，只更新发布身份。

**完整离线安装**

离线安装包按 CPU 架构发布，并包含 PostgreSQL、Redis、MinIO、LiteLLM、DramaForge 前后端
等全部镜像。解压后运行：

```powershell
.\install.ps1 -Offline
```

或：

```sh
./install.sh --offline
```

安装器会从包内 `images.tar` 导入镜像，并通过 `docker-compose.offline.yml` 强制禁止拉取。
“离线安装”只表示安装过程不访问镜像仓库；使用 Agnes、MiniMax 等云 Provider 创作仍需外网
和用户自己的密钥。首版尚未宣称整条媒体创作链可断网运行。

安装器为 Session、Worker、BYOK Fernet 和 LiteLLM 分别生成唯一密钥，且不会把密钥单独
打印到终端。需要保留的 Provider BYOK 只写入本地 `.env`。Compose 对必需密钥采用
fail-fast 校验，空值或缺失时不会启动。

默认部署为单用户模式（`PUBLIC_REGISTRATION_ENABLED=false`）：干净数据库允许在登录页创建
第一个 Owner；创建成功后后端 `/api/v1/auth/register` 返回 `REGISTRATION_CLOSED`，前端也会
隐藏初始化入口。不要为了“修复登录”删除数据库。只有明确需要多账号实验时，才在受控环境将
该变量改为 `true`。

Compose 会从本地忽略的 `.env` 读取 `AGNES_*`、`TEXT_LLM_*` 和可选的 `TTS_*`，
并仅注入 API 与 Worker 容器；未配置时保持 fail-closed。不要把真实密钥写入
`docker-compose.yml` 或提交到 Git。

> 安装会启动 **所有** 服务（postgres、redis、minio、litellm、migrate、api、frontend、dispatcher、worker-default、worker-heavy）。后端成品镜像包含 FFmpeg 与 eSpeak NG；人物一致性由参考绑定、有效请求、产物血缘和人工试拍验收共同判断。

**验证**

```powershell
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health
# → {"status":"ok","db":"up"}
```

浏览器打开 `http://localhost:8080`。默认只绑定回环地址，不提供 TLS；公网或局域网部署必须
明确配置入口与 HTTPS 边界，详见
[`docs/runbooks/docker-deployment.md`](docs/runbooks/docker-deployment.md)。

**GPU / ComfyUI（可选）**：

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up -d
```

---

### 容器内开发与调试

项目的运行时、依赖安装、静态检查、测试和 E2E 统一在 Docker 容器中执行。
宿主机不创建 Python venv、不安装 Node 依赖，也不直接启动 API 或 Vite。
需要断点时，让 IDE 附加到对应容器进程；这不会改变 8080 唯一用户入口。

从源码构建并启动完整应用：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

`docker-compose.dev.yml` 只显式开放基础设施调试端口，不得用于不受信网络。数据库、队列、
对象存储和 API 仍由 Compose 管理，API 的 8000 端口不发布到宿主机。

需要从源码构建完整容器栈时，必须显式叠加构建 override：

```powershell
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

发布拓扑本身没有 `build` 字段；改动源码后由开发者或 CI 重新构建镜像，普通用户不在安装机
上编译。

Worker、API 和前端网关均由 Compose 管理。工作台壳使用 TanStack Router + QueryClient；
服务端状态只放 TanStack Query，Zustand 仅保存布局/选择等 UI 状态。

## 测试与质量门禁

提交前的权威质量门禁在 Docker 中执行。它会在一次性质量容器内安装锁定的
Python/Node 依赖，运行后端静态检查、单测、PostgreSQL 迁移/API 合同，以及前端
lint/typecheck/unit/build/E2E；宿主机不需要安装 Python、uv、Node 或浏览器：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

其中 Canonical surface scan 会阻止已删除的 Quick、Creation、受控 Director、
CharacterReference、旧运行时开关和旧 NodeRun 字段重新出现。

`scripts/run_quality.ps1` 仅作为兼容入口，内部转发到同一个 Docker Gate；不要在宿主机
另行安装或运行项目工具链。

演示目录检查的拒绝路径：

```powershell
python .\scripts\check_directory_compliance.py --demo-unregistered utils2 --demo-sensitive .env
```

## 开始开发（Agent）

编码 Agent 必须先读取：

1. [`agent.md`](agent.md)
2. [`AGENT_EXECUTION_PROTOCOL.md`](AGENT_EXECUTION_PROTOCOL.md)
3. [`docs/plans/professional-program-v2/README.md`](docs/plans/professional-program-v2/README.md)
4. 当前 Task Contract，以及它按类型指定的七方案原文
5. 本机 `.agent-control/PROGRESS.jsonl` 尾部和 `open` 结果
6. 当前代码、迁移、测试、ADR 与仅作操作参考的 Runbook

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation open
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation tail -Tail 20
git status --short
git worktree list
git branch --all
git remote -v
```

每个任务开始、完成、失败或暂停时，通过 `.agent-control/control.ps1 -Operation log` 追加事实记录。日常开发在根 worktree 的本地 `dev` 分支进行；Task 合同和验证通过后提交。除非 Owner 明确要求，不推送到 `origin/dev`。`main` 只保留经过验证的稳定版本，并且只能通过 `dev -> main` 的受保护 PR 更新。需要并行隔离或紧急修复时，才从当前本地 `dev`（紧急修复从 `main`）创建短期 `agent/<task-id>` 分支和 `.worktrees/<task-id>`，其 PR 先合回 `dev`（紧急修复合回 `main` 后也要同步回 `dev`）。Agent 不得批准、合并或记录 `MERGED`；只有 `@zwb2002-yjy` 可以在批准并合并 PR 后记录该状态。GitHub Ruleset 配置见 [`docs/runbooks/github-ruleset.md`](docs/runbooks/github-ruleset.md)。

发布或 tag 前，从候选 commit 的干净 worktree 执行 [`docs/runbooks/release-gate-board.md`](docs/runbooks/release-gate-board.md) 要求的自动化、真实 Provider、用户、离线和安装证据。报告写入 `tmp/p0-evidence/<sha>/`，并绑定 commit、dirty 状态、环境和 source 一致性；任何 `FAIL`、`BLOCKED` 或 source mismatch 都禁止发布。

Agent 不以完成一个 Task 作为停机条件。每个 Task 开始前先在当前计划目录的 Task Contract 定义可观察效果和验收证据；完成并提交后按七方案重算当前 Gate，继续最高优先级的 `READY` Task。外部条件只暂停依赖它的路径；后续能力按当前总纲和架构确认表重新进入，不沿用已删除的旧阶段标签。

## 产品阶段

当前产品、技术与实施依据为 Owner 指定并已内化的七方案；请从 [`DramaForge总开发文档.md`](DramaForge总开发文档.md) 或 [`docs/plans/professional-program-v2/README.md`](docs/plans/professional-program-v2/README.md) 进入。旧 `docs/current/` 和此前总纲不再定义开发范围。

## 开源治理

DramaForge 以 [Apache License 2.0](LICENSE) 开源。提交代码前请阅读
[贡献指南](CONTRIBUTING.md)、[安全策略](SECURITY.md)、
[社区行为准则](CODE_OF_CONDUCT.md) 与 [第三方声明](THIRD_PARTY_NOTICES.md)。

仓库提供 AIOS/AISphere 的 Compose 交接描述，但尚未在真实 AIOS 环境验证，也没有冒充平台
官方 manifest；边界与集成验收见
[`docs/runbooks/docker-deployment.md`](docs/runbooks/docker-deployment.md)。
