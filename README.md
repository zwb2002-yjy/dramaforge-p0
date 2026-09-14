# DramaForge

DramaForge 是面向专业个人创作者的开源 AI 影视制作工作台。首版聚焦围绕场景、镜头和资产完成一部
15–30 秒、真人写实风格、角色对白驱动的多镜头短剧：生成前确认创作与拍摄方案，用代表
镜头试拍降低盲抽成本，失败后提供有证据和成本范围的局部修复，并保留完整产物血缘。

唯一开发工作区是仓库根目录 `D:\dramaforge`；`D:\项目` 只保存外部研究资料，不写入任何代码、迁移、
测试或 fixture。

## 当前状态

产品、技术、模型供应与阶段顺序的唯一依据是项目 Owner 指定并已内化的
[Professional 七方案执行集](docs/plans/professional-program-v2/README.md)（根入口为
[`DramaForge总开发文档.md`](DramaForge总开发文档.md)），以及其后的 Owner amendments 和
[Task Contract](docs/plans/professional-program-v2/task-contracts/)。代码、迁移、测试与运行证据
说明“现在实际是什么”；历史 P0、旧总纲、旧 `docs/current/` 合同和旧 Release Board 的通过记录都不能
替代当前 Task 的证据。当前事实清单见 [`docs/architecture/`](docs/architecture/)，文档导航见
[`docs/README.md`](docs/README.md)。

首版不集成人脸 embedding、生物特征识别或相似度阈值；没有可信且校准过的自动评估器时，人物一致性
返回 `needs_human`，不伪造通过分数。

## 快速开始

宿主机只需要 Docker Compose v2，不需要 Python、Node.js 或编译器。

```powershell
# 在线安装：从同一个 GitHub Release 解压完整安装包后运行
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Linux/macOS 用 `chmod +x install.sh && ./install.sh`；完整离线安装包用 `.\install.ps1 -Offline`
或 `./install.sh --offline`（离线只表示安装过程不访问镜像仓库，云 Provider 创作仍需外网和自带密钥）。

安装会启动全部默认服务，其中只有前端网关发布宿主端口：

```powershell
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health          # → {"status":"ok","db":"up"}
```

浏览器打开 `http://localhost:8080`。默认只绑定回环地址且不提供 TLS，公网或局域网部署的入口与
HTTPS 边界见 [`docs/runbooks/docker-deployment.md`](docs/runbooks/docker-deployment.md)。

## 开发与质量门禁

运行时、依赖安装、静态检查、测试和 E2E 统一在 Docker 中执行；宿主机不创建 Python venv、不安装
Node 依赖，也不直接启动 API 或 Vite。

```powershell
# 从源码构建并启动完整栈
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build

# 权威质量门禁：后端扫描/静态检查/单测/迁移与集成测试/OpenAPI 合同，
# 前端 API 合同校验/format/lint/typecheck/单测/构建/E2E
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

`docker-compose.dev.yml` 只额外开放基础设施调试端口，不得用于不受信网络。发布拓扑本身没有 `build`
字段：普通用户消费版本化镜像，不在安装机上编译。

## Agent 入口

编码 Agent 先读 [`agent.md`](agent.md)、[`AGENT_EXECUTION_PROTOCOL.md`](AGENT_EXECUTION_PROTOCOL.md)
与[七方案执行集](docs/plans/professional-program-v2/README.md)，再按当前
[Task Contract](docs/plans/professional-program-v2/task-contracts/) 的范围实施。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation open
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation tail -Tail 20
```

日常开发在根 worktree 的本地 `dev` 分支进行，`main` 只能通过受保护的 `dev -> main` PR 更新；
只有 `@zwb2002-yjy` 可以批准、合并并记录 `MERGED`。发布证据要求与操作步骤见
[`docs/runbooks/`](docs/runbooks/)，报告写入 `tmp/p0-evidence/<sha>/` 并绑定 commit 与 source 一致性。

## 开源治理

DramaForge 以 [Apache License 2.0](LICENSE) 开源，提交前请阅读[贡献指南](CONTRIBUTING.md)、
[安全策略](SECURITY.md)、[社区行为准则](CODE_OF_CONDUCT.md) 与[第三方声明](THIRD_PARTY_NOTICES.md)。
仓库提供 AIOS/AISphere 的 Compose 交接描述，但尚未在真实 AIOS 环境验证。
