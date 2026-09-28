# DEVELOPMENT — 开发与测试权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

## 原则

运行时、依赖安装、静态检查、测试和 E2E 统一在 Docker 中执行；宿主机不创建
Python venv、不安装 Node 依赖，也不直接启动 API 或 Vite。

## 本地开发

```powershell
# 从源码构建并启动完整栈
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

前端网关是唯一宿主应用入口：http://127.0.0.1:8080。
`docker-compose.dev.yml` 额外开放基础设施调试端口，不得用于不受信网络。

## 权威质量门

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

（Linux/macOS 用 scripts/run_quality_in_docker.ps1 中的等价 Docker Compose 命令。）
该门构建 backend 质量容器（Python 3.14.x / Debian Bookworm）与 frontend 质量容器
（Node 24 LTS + Chromium），执行：

- 目录合规、canonical-surface 与增量架构依赖门（`arch_import_scan.py --check`）、ruff、mypy；
- backend 单测；
- PostgreSQL `alembic upgrade head` / `alembic check` 与集成测试；
- OpenAPI 导出与 generated client 检查；
- 前端 format / lint / typecheck / Vitest / 生产构建 / 生产路由注册检查 / Playwright E2E；
- LiteLLM 集成（固定官方 Proxy 镜像 + 确定性 mock 模型，无外部 Provider 调用）。

本地完整质量门与 GitHub Full Gate 共用 `docker-compose.quality.yml`，不维护第二套
测试实现。GitHub PR CI 按变更风险分层：

- 所有 PR：`policy` + secret scan；
- docs-only：不构建 backend/frontend 质量镜像，不启动 PostgreSQL、Redis、
  Playwright、LiteLLM，也不执行依赖审计；
- 普通 backend-only：backend 镜像 + ruff / mypy / backend unit；
- 普通 frontend-only：frontend 镜像 + format / lint / typecheck / Vitest / build / routes:check；
- migrations、API contract、Director/Production Runtime、Provider/Worker、
  Docker/Compose/infra/workflow，以及同时修改 backend + frontend 的 PR：
  升级为完整 `container-gates`；
- Python / Node 依赖审计仅在对应依赖描述或 lockfile 变化、`dev -> main`
  或手动完整门时执行；
- Trivy filesystem scan 在高风险/依赖变更、`dev -> main` 或手动完整门执行；
- 同一 PR 的新 commit 会取消旧的未完成 CI，避免验证已过期 SHA。

常规 merge 到 `dev` 后不再原样重复 PR 全量质量门；发布候选和
`dev -> main` 仍执行完整验证。周度完整安全扫描由
`.github/workflows/security.yml` 独立执行。

质量 Dockerfile 先安装 lockfile 对应依赖，再复制完整源码，使本地/self-hosted
以及具有可复用构建缓存的环境不会因普通源码或文档变化无意义重新安装全部依赖。

运行时基线为 Node 24.x、Python 3.14.x；Docker 标签允许系列内维护更新，
不是不可变的补丁版本 / digest 锁定。Dependabot 的常规版本更新先进入 `dev`，
Node 跨主版本、Python 跨次版本升级由独立任务评估。安全更新仍依 GitHub
默认分支机制处理；本地版本选择文件位于 `frontend/.nvmrc` 和
`backend/.python-version`。

## 零成本运行时 smoke

从 backend runtime 容器运行 canonical proof 脚本（宿主机无需 Python）：

```text
docker compose --profile maintenance run --rm --entrypoint python maintenance \
  /workspace/scripts/prove_formal_live_chain.py --scratch /workspace/tmp/proof \
  --idea "..." --script-file /workspace/fixtures/scripts/episode_script.md
```

保留的证明 / 验收驱动脚本（`scripts/prove_*.py`）内置安全边界：付费阶段
必须显式 `--real` 才会发起 HTTP；证据脱敏（去除 secret、签名 URL、
basic-auth）；断点续跑不重复已成功请求。

## 真实 Provider 证据（付费边界）

真实 Provider 证明需要独立的正数预算与 Owner 明确授权，且：

- 先运行不付费的"认证 / 模型目录"探测；
- 记录 exact source commit 与脱敏 ProviderOperation 证据；
- `unknown_submission` 不盲目重试；
- 证据写入 `tmp/p0-evidence/<source-commit>/`（gitignored，不入库）；
- 不提交从 dirty worktree 生成的正式证据。

## 故障排查

- API health：http://127.0.0.1:8080/health；网关：/gateway-health；
- 用 `docker compose ps` / `docker compose logs` 检查内部服务；
- 质量镜像构建失败时先修复 Docker Hub / Debian / npm 网络访问；
  不得用宿主机安装的依赖替代并把门报绿。

## 备份与恢复

```text
docker compose --profile maintenance run --rm maintenance backup --out /workspace/tmp/<name>.tar
docker compose --profile maintenance run --rm maintenance restore-verify \
  --archive /workspace/tmp/<name>.tar --restore-database-url <dsn> --restore-bucket <bucket>
```

### 生产路由与 API 契约复现

- `npm run --prefix frontend routes:check` 用项目 Vite production transforms 编译真实
  router，并在 Chromium 读取 `routesByPath`；必须保留核心业务路由且不得注册
  `/design-preview`。它不以 UI 隐藏或开发服务器的 404 作为生产证据。
- 完整门先从当前后端导出 OpenAPI，再运行 `api:check`，重生成并逐字节比较
  `frontend/src/shared/api/generated.ts`；`api:authority` 同时拒绝手写重声明生成的
  API schema。检查不会改写提交中的 generated.ts。
