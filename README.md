# DramaForge

DramaForge 是面向专业个人创作者的开源 AI 短剧 / 漫剧导演工作台。以场景（Scene）、
镜头（Shot）和资产（Asset）组织创作，把剧本、分镜、模型生成、审片修复与剪辑成片
放在同一个项目中，并保留每次生产的模型身份、输入、执行记录与产物血缘。

**当前处于未发布开发阶段，最新开发源码在 `dev`。** 首版目标是一部 15–30 秒、
真人写实风格、角色对白驱动的多镜头短剧，交付 MP4 与 SRT；这是验收目标，
不限制项目的时长或镜头数。源码整合、服务健康和局部测试通过均不等于正式发布完成。
当前发布条件见 [V1_STATUS.md](docs/V1_STATUS.md)。

## 创作工作流

```text
故事 / 剧本 → 角色与素材 → 场景 / 分镜 → 视频生成 → 审片 / 局部修复 → 剪辑 → MP4 + SRT
```

当前工作台围绕以下工作区组织：

| 工作区 | 当前能力 |
|---|---|
| 项目总览 | 模板或自由创建、导演自主性设置、制作状态与批量补齐确认 |
| 故事剧本 | 剧本导入与编辑，组织 Episode / Scene / Shot |
| 角色与素材 | 资产版本、参考素材与显式身份绑定 |
| 分镜制作 | 中央画布、镜头条、镜头检查器、候选托盘；保存设计后预览并确认生成 |
| 审片确认 | 查看候选、人工审核、证据批注、局部修复与正式产物选择 |
| 剪辑成片 | 时间线编辑与保存、配音及字幕、导出绑定时间线版本的 Final Film |

视频输入包括文生视频、正式首帧、尾帧、首尾帧和已保存参考素材；可用方式由具体
模型合同与输入条件决定。候选预览、人工审核通过和「设为正式」是独立操作。
导演建议先应用到草稿，保存后才建立正式设计；Apply / Save / Formal / Export
分别由用户明确触发。

创作体验改进与 Director Agent 的后续设计仍有未完成的开发和验收项，
范围见 [CURRENT.md](docs/CURRENT.md)，不能将目标章节视为已交付功能。

## 模型与供应商配置

DramaForge 使用自带密钥（BYOK）。在「模型设置」中添加供应商名称、服务地址和 Key，
读取模型目录后，分别启用所需的文本、图片与视频模型。界面提供 Agnes、MiniMax、
Seedance 预设，以及自定义媒体服务和独立 LLM 连接；具体可执行能力以版本化模型合同
和当前连接验证结果为准。

- 多个连接独立保存地址与凭证；启用模型只切换对应用途，同名模型保留各自连接身份。
- 自定义模型必须匹配受支持的调用合同；目录中出现某个 ID 不等于支持任意生成方式。
- 文本通道可连接官方 LiteLLM Proxy 或兼容端点；当前默认 Compose 包含本地 LiteLLM。
- 生成前预览并确认执行计划，模型、参数与参考素材身份随执行冻结；执行时不静默换模型。
- 批量补齐在确认前列出生成、跳过和需处理的镜头，并绑定本次预览与操作数上限。

Provider 费用由供应商账户结算，DramaForge 不维护金额预算、余额或 credits。
新的付费生成与修复需要明确授权；已提交任务的查询、下载和恢复复用原执行身份，
提交结果未知时不盲目重试。模型目录与连接检查不证明作品质量。
详细支持范围见 [MODEL_PROVIDER.md](docs/MODEL_PROVIDER.md)。

## 从源码快速开始

准备 Git、Docker Compose v2（Windows/macOS 使用 Docker Desktop）和 Python 3。
Python 只用于首次运行标准库环境初始化脚本，无需安装后端依赖；应用运行在容器中。

```text
git clone --branch dev https://github.com/zwb2002-yjy/dramaforge-p0.git
cd dramaforge-p0
python scripts/init_env.py
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

初始化脚本生成独立密钥和 `.env`，自动记录当前 Git 提交，并拒绝覆盖已有 `.env`。
默认 Compose 项目名为 `dramaforge-dev`，仅网关发布宿主端口 `127.0.0.1:8080`。
首次打开 [本地工作台](http://localhost:8080) 创建 Owner 账户，再配置模型。
首次 Owner 初始化后，默认关闭公开注册。

```text
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health
docker compose ps
```

健康检查只证明网关/API 与数据库就绪。更新源码后保留原 `.env` 与数据卷，
将 `DRAMAFORGE_SOURCE_COMMIT` 更新为 `git rev-parse HEAD` 的结果再重建；镜像、API、
Workers 必须对应同一提交。旧实例数据卷单独保管，不自动合并数据或启动旧任务。
公网入口、HTTPS 和备份恢复见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。

### 版本化安装包

正式 Release 完成后，安装应使用同一 GitHub Release 的完整制品。Windows 运行
`.\install.ps1`，Linux/macOS 运行 `chmod +x install.sh` 后执行 `./install.sh`。
完整离线包分别使用 `.\install.ps1 -Offline` 或 `./install.sh --offline`。

安装包宿主机只需要 Docker Compose v2，无需 Python、Node.js 或编译器。
离线安装表示安装过程不访问镜像仓库；云 Provider 创作仍需网络和自带密钥。
当前源码试用使用上面的构建入口，安装包合同见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 架构与技术栈

Director Runtime 使用 LangGraph 负责提案与编排；Production Runtime 负责真实生产。
媒体统一经过冻结执行计划 → ProductionGraph / NodeRun → ProviderOperation → Artifact，
剪辑通过 EditSession 使用正式产物，导出绑定时间线版本。

| 层 | 技术 |
|---|---|
| 前端 | React 18、TypeScript、Vite、TanStack Router / Query、Zustand，自有设计系统 |
| API 与领域服务 | FastAPI、Pydantic、SQLAlchemy、Alembic |
| 导演与异步执行 | LangGraph、PostgreSQL checkpoint、Arq / Redis、dispatcher 与分队列 Workers |
| 数据与媒体 | PostgreSQL 15、MinIO、FFmpeg |
| 部署 | Docker Compose、Nginx 网关、独立 LiteLLM Proxy |

```text
backend/    API、领域服务、Workers、迁移与测试
frontend/   工作台、设计系统与前端测试
infra/      LiteLLM、Nginx 等运行配置
scripts/    质量门、发布、验收与维护脚本
fixtures/   自动化测试固定输入
docs/       当前权威文档与技术决策
deploy/     部署交接描述
.github/    CI、Release 与安全工作流
```

## 开发与验证

运行时、依赖安装、静态检查、测试和 E2E 统一在 Docker 中执行。
宿主机不创建 Python venv、不安装 Node 依赖，也不直接启动 API 或 Vite。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

完整质量门覆盖目录与架构规则、后端静态检查和单测、PostgreSQL 迁移及集成测试、
OpenAPI / 前端 API 合同、format / lint / typecheck / Vitest / 构建 / Playwright，
以及固定 LiteLLM Proxy 与确定性 mock 的集成测试；不调用真实外部模型。
脚本会清理其 quality 项目的容器与卷，运行前核对资源归属。
文档改动采用链接与差异等必要检查，发布候选仍须完整验证。
详细命令和验证边界见 [DEVELOPMENT.md](docs/DEVELOPMENT.md)。

日常开发在 `dev` 集成。当前 CI 监听指向 `main` 的 PR 与手动 dispatch，
`dev` 推送本身不代表质量门通过。`main` 通过受保护的 `dev -> main` PR 更新，
仅由 `@zwb2002-yjy` 批准和合并；发布步骤见 [RELEASE.md](docs/RELEASE.md)。

## 文档与贡献

**[docs/CURRENT.md](docs/CURRENT.md) 是所有当前权威文档的唯一入口。**
产品、架构、Runtime、模型、数据、API、前端、开发、部署和发布各有明确归属。
代码、迁移、测试与运行证据建立当前事实；历史方案和执行记录通过 Git 历史追溯。
编码 Agent 先读 [AGENTS.md](AGENTS.md)，再从该入口定位所需文档。

DramaForge 以 [Apache License 2.0](LICENSE) 开源。贡献前请阅读
[贡献指南](CONTRIBUTING.md)、[安全策略](SECURITY.md)、
[社区行为准则](CODE_OF_CONDUCT.md) 与[第三方声明](THIRD_PARTY_NOTICES.md)。
仓库提供 AIOS/AISphere 的 Compose 交接描述，尚未在真实 AIOS 环境验证。
