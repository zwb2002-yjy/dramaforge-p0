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

完整脚本在开头及结束时对 quality Compose 执行 `down --volumes --remove-orphans`。
运行前核对它的项目名和资源归属，不与使用同一 quality 项目的其它会话并行；它不是
现有开发/生产实例的清理工具。普通 docs-only 改动不因新增验收文字就运行完整门。

## 运行健康检查与真实验收驱动的区别

`/health`、`/gateway-health` 和容器状态仅证明运行与来源信息，不能证明创作、Provider
或作品质量。不能将所有 `scripts/prove_*.py` 统称为“零成本 smoke”，也不能假设它们
都有 `--real` 或金额预算开关。以下是当前源码中的主要差异：

| 脚本 | 实际边界 | 使用要求 |
|---|---|---|
| [prove_formal_live_chain.py](../scripts/prove_formal_live_chain.py) | 有注册/创建工作空间、项目和 executions 写入；无 `--real` / 数字预算参数 | 不作只读或免费检查；先核对实例、身份、具体调用及逐操作授权 |
| [prove_professional_agnes_golden.py](../scripts/prove_professional_agnes_golden.py) | 创建并生成真实关键帧/视频；无 `--real` / 数字预算参数 | 是真实 Provider 驱动，不能以脚本名称代替预算/授权 |
| [prove_v1_r7_acceptance.py](../scripts/prove_v1_r7_acceptance.py) | 付费阶段有 `--real`/candidate 检查；preflight 无 Provider 调用但会写 profile、项目、绑定 | preflight 也需要明确的测试环境与写入范围；`--real` 不是 Owner 授权或费用上限 |

第三个脚本当前默认 base URL 是 8088，并非产品网关 8080；执行时必须核对并显式指定
已经安排的目标实例，不能只把端口改成当前可访问实例。脚本支持的参数以 argparse 为准，
不向没有该参数的脚本追加 `--real` 并声称安全。源码阅读可以发现边界，不代表脚本在新
候选上已验证；恢复与脱敏仍需在相应候选上用证据确认。

## 真实 Provider 证据（付费边界）

真实 Provider 证明需要独立的正数预算与 Owner 明确授权，且：

- 优先运行协议明确支持且不计费的认证/目录检查；无此接口时不能伪造通过，按 MODEL_PROVIDER
  的 MP-04/MP-11 目标完成受控验证合同前，保留现有付费探测拒绝；
- 记录 exact source commit 与脱敏 ProviderOperation 证据；
- `unknown_submission` 不盲目重试；
- 证据写入 `tmp/p0-evidence/<source-commit>/`（gitignored，不入库）；
- 不提交从 dirty worktree 生成的正式证据。

## 创作体验开发合同的验证分层

需求与断言唯一索引见 [ARCHITECTURE_MAPPING.md §6](ARCHITECTURE_MAPPING.md#creation-improvement-contract)。
以下不是新增脚本清单，也不表示本次文档编写已完成产品测试。

| 层级 | 覆盖内容 | 通过能说明什么 |
|---|---|---|
| 文档检查 | `git diff --check`；核对相对链接、显式锚点、需求编号、范围和目标状态一致性 | 文档可读取且无已发现合同冲突；不证明实现 |
| 离线行为回归 | mock 协议、compiler/wire、API/权限/幂等、前端状态与 DOM/网络断言 | 可重复的用户行为与拒绝路径，不证明真实账号可用 |
| 数据与恢复集成 | PostgreSQL 前向迁移/RLS、冻结历史、Outbox/租约/重启与未知提交 | 身份、隔离、单次提交及恢复正确；不能以 SQLite 替代 |
| 容器完整门 | 现有权威质量脚本及 CI required checks | 当前候选满足代码、契约、构建和集成门；不证明作品可接受 |
| 体验与资源 | AC-10/11/14/17 固定视口、媒体 fixture、时间精度、RSS/并发/查询测量 | 在声明硬件与负载上达标；不推广成任意设备性能保证 |
| 真实样片与作品评审 | AC-18 精确模型/模式、逐操作授权、人工评审与一次受控修改 | 该候选/模型组合能完成并打磨样片；不保证所有提示词或所有供应商 |

开发切片先补必要行为回归，再执行受影响门。Provider/API/Worker/迁移或前后端联合变更
触发完整容器门，不能凭局部测试数绕过 CI。离线测试与 CI 门不得真实调用外部模型；mock 只覆盖协议与
状态，不能编造“官方质量认证”。动态分镜、同源请求预览和资源基准缺少的驱动随实现补齐，
当前不提供不存在的命令。性能证据必须注明缓存、采样数量、并发、容器限制与排除项。

验收结果逐 AC 编号记录通过/失败/未运行与证据位置。技术错误、交互阻断和作品判断分开：
FFmpeg 解码成功不证明叙事成立，人工喜欢画面不放行重复扣费或身份错误。作品评审缺少
预算、真实素材或 Owner 判断时保留未验收状态；不通过改写初始创作目标获得通过。

证据写入任务自己的 gitignored `tmp/`，最终候选证据再按既有发布路径管理。保留原截图，
使用 DOM、可访问性、网络/console、尺寸/hash和断言为主；图像读取遵守根 AGENTS.md。
不要在证据中输出 Key、Authorization、签名 URL、base64 或完整私有创作快照。

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
  `frontend/src/shared/api/generated.ts`；`api:authority` 同时拒绝 API client 中同名或异名手写的
  API schema。检查不会改写提交中的 generated.ts。
