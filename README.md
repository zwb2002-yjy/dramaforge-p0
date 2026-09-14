# DramaForge

DramaForge 是面向专业个人创作者的开源 AI 影视制作工作台。首版聚焦围绕场景、
镜头和资产完成一部 15–30 秒、真人写实风格、角色对白驱动的多镜头短剧：生成前
确认创作与拍摄方案，用代表镜头试拍降低盲抽成本，失败后提供有证据和成本范围的
局部修复，并保留完整产物血缘。

**所有当前权威文档的入口是 [docs/CURRENT.md](docs/CURRENT.md)**：产品、架构、
两个 Runtime、模型供应、数据模型、API、前端、当前 V1 状态、开发、部署与发布
各有一份权威文档。历史设计、Task Contract、Review 和执行记录只存在于 Git
历史中，不构成当前实现依据。

## 快速开始

宿主机只需要 Docker Compose v2，不需要 Python、Node.js 或编译器。

```powershell
# 在线安装：从同一个 GitHub Release 解压完整安装包后运行
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Linux/macOS 用 `chmod +x install.sh && ./install.sh`；完整离线安装包用
`.\install.ps1 -Offline` 或 `./install.sh --offline`（离线只表示安装过程不访问
镜像仓库，云 Provider 创作仍需外网和自带密钥）。

安装会启动全部默认服务，其中只有前端网关发布宿主端口：

```powershell
curl http://localhost:8080/gateway-health
curl http://localhost:8080/health          # → {"status":"ok","db":"up"}
```

浏览器打开 `http://localhost:8080`。公网或局域网部署的入口与 HTTPS 边界见
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 开发与质量门禁

```powershell
# 从源码构建并启动完整栈
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build

# 权威质量门：后端扫描/静态检查/单测/迁移与集成测试/OpenAPI 合同，
# 前端 API 合同校验/format/lint/typecheck/单测/构建/E2E
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

运行时、依赖安装、静态检查、测试和 E2E 统一在 Docker 中执行；宿主机不创建
Python venv、不安装 Node 依赖，也不直接启动 API 或 Vite。详见
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## Agent 入口

编码 Agent 先读 [AGENTS.md](AGENTS.md)，再按 [docs/CURRENT.md](docs/CURRENT.md)
定位权威文档；实施以代码、迁移、测试和运行证据为现状基线。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation open
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation tail -Tail 20
```

日常开发在根 worktree 的本地 `dev` 分支进行，`main` 只能通过受保护的
`dev -> main` PR 更新；只有 `@zwb2002-yjy` 可以批准、合并并记录 `MERGED`。
分支保护与发布步骤见 [docs/RELEASE.md](docs/RELEASE.md)。

## 开源治理

DramaForge 以 [Apache License 2.0](LICENSE) 开源，提交前请阅读[贡献指南](CONTRIBUTING.md)、
[安全策略](SECURITY.md)、[社区行为准则](CODE_OF_CONDUCT.md) 与[第三方声明](THIRD_PARTY_NOTICES.md)。
仓库提供 AIOS/AISphere 的 Compose 交接描述，但尚未在真实 AIOS 环境验证。
