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
`docker-compose.dev.yml` 只把 PostgreSQL/Redis/MinIO/LiteLLM 调试端口发布到回环地址，
不改变基础栈的内部网络边界；该 opt-in 文件仍不得用于不受信网络。

## 权威质量门

### 日常反馈与收尾

开发期间使用现有入口的定向模式（每次构建当前源码，复用锁定依赖的 Docker 缓存）：

```powershell
.\scripts\run_quality_in_docker.ps1 -Stage BackendTests -TestArgs @('tests/unit/test_ci_workflow_contract.py', '-q')
.\scripts\run_quality_in_docker.ps1 -Stage FrontendTests
```

BackendTests 默认执行后端 unit；FrontendTests 默认执行 Vitest，可用 TestArgs 传递
测试路径/过滤参数。参数直接传给测试程序，不拼接 shell。定向模式禁用容器网络，
不启动 PostgreSQL、Redis 或真实 Provider，不执行 Compose down，不生成额外报告目录。
因此它不适用于需要外部服务的集成测试，也不代表 Full Gate 通过。

一次任务按“修改 → 相关测试 → 修复失败 → 受影响回归 → 合同要求的完整门”推进。
已通过检查仅在相关源码、依赖、环境变化或存在未解决疑点时重跑；小修改无需每次
执行完整门。文档改动检查差异、相关链接与合同；高风险变更和发布的完整门要求仍有效。
最终报告给出改动范围、源码/工作区状态、实际命令及结果、未运行项和剩余决策即可。
修改历史由 Git 保存，日常结果记在对话中；不要每轮新增日期命名的测试、审计或计划文件。

不带参数（或 `-Stage Full`）仍运行下述完整门。Full 拒绝 TestArgs，防止过滤测试后
误报全量通过。前端完整门的类型检查由 `npm run build` 执行一次。

后端本地项目安装使用共享 BuildKit uv 缓存。已有基础镜像与锁定依赖层、并且 uv
构建依赖缓存完整时，可加 `-OfflineProjectInstall` 让源码复制后的本地包安装禁止联网；
缓存缺失会失败，不切换包源、不安装宿主依赖。此参数只约束本地 Python 包安装步骤，
不宣称整个 Docker 构建或 Full Gate 都无需网络。缓存不是验收结果：仍须构建当前源码，
以本次镜像身份运行测试；依赖锁文件匹配不能证明旧镜像的源码匹配。
质量容器运行阶段统一使用已安装的环境：`uv run --offline --no-sync` 或直接调用
`.venv/bin`。依赖安装只发生在构建阶段，不能在每个检查开始时再次解析/重装项目。

### 产物生命周期

- 测试代码按行为维护，修复优先扩展现有用例；删合用例前核对独立风险、拒绝路径与覆盖。
- 临时运行产物归任务自己的 gitignored `tmp/`；优先复用 Docker 构建缓存，避免复制
  node_modules、完整源码和重复镜像包。需要脱离源码的安装验证仍使用独立目录。
- 本任务创建的可再生中间产物，在问题解决、验证完成且确认不再引用后可收尾；失败
  尚未解释的日志/trace/截图保留。不能仅按年龄、文件名或“提交已合并”判断可删除。
- 原始验收截图、正式候选证据、付费操作事实、备份和持久数据按既有规则保留；
  哈希不替代原件。跨任务的历史资源先列出绝对路径、用途、占用、引用和归属，
  获得 Owner 明确处置范围后再归档或删除，不自动执行 TTL 清理。
- worktree 有未提交修改、未集成提交或使用状态不明时不回收；不终止其他会话。

### 专项 Agent 合同与集成

主 Agent 独占 CURRENT、架构权威、baseline、共享 CI/Compose 和最终验收；专项 Agent
按明确目录/文件拥有写权，不能同时修改同一权威。每个合同必须给出目标、可写范围、
不可变边界、验收标准、来自现有配置的验证命令、回滚边界；未授权文件只提交建议。
只读审计先列真实消费者、职责、替代影响和验证成本；再决定 KEEP/收敛/Owner 决策。
LangGraph、生产事实链、用户门、执行身份和付费授权不是依赖精简的可选项。

专项执行聚焦回归，主 Agent 在整合后的当前源码上统一运行受影响门及必要完整门。
提交前核对其他会话改动；回滚只还原本切片代码，不删除历史事实、证据或数据卷。
活跃跨模块任务归 ARCHITECTURE_MAPPING；结果在对话/既有证据中报告，完成后不保留
逐轮任务副本或新建平行治理规则库。

### 完整验证

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
```

（Linux/macOS 用 scripts/run_quality_in_docker.ps1 中的等价 Docker Compose 命令。）
该门构建 backend 质量容器（Python 3.14.x / Debian Bookworm）与 frontend 质量容器
（Node 24 LTS + Chromium），执行：

- 目录合规、canonical-surface、Provider 权威、增量架构依赖门（`arch_import_scan.py --check`）、
  模型支持文档生成一致性（`generate_model_support_docs.py --check`）、ruff、mypy；
- backend 单测；
- PostgreSQL `alembic upgrade head` / `alembic check` 与集成测试；
- OpenAPI 导出与 generated client 检查；
- 前端 format / lint / typecheck / Vitest / 生产构建 / 生产路由注册检查 / Playwright E2E；
- 实际 Nginx 配置认证边界（独立 synthetic upstream/第二 TCP 客户端），验证限流、
  429/Retry-After、伪造 IP 头、跨客户端隔离与窗口恢复；业务认证另由 API 单测覆盖；
- LiteLLM 集成（固定 digest 官方 Proxy + 独立数据库、内核 namespace ACL、计数 Mock
  上游；覆盖重试覆盖、同名创建竞争、凭据覆盖、重定向及 metadata 拒绝，无外部 Provider 调用）。

`scripts/check_litellm_runtime_contract.py` 对同一 synthetic quality stack 自动演练 Proxy
DB 备份/恢复与 guard/Proxy namespace 重建，保留同一部署 ID、SALT 和上游请求计数证据。
它只允许专属 quality 服务和合成管理 Key，所有数据库/Provider 请求仍在容器内执行；
宿主 Python 仅用标准库编排 Docker，不提供应用测试依赖。证据必须写入新的 `tmp/` 目录。

LiteLLM 集成进程共享受限网络命名空间，使用镜像构建阶段已安装的锁定依赖与本地包。
运行命令直接调用 `/workspace/backend/.venv/bin/pytest`，不在运行时解析或同步依赖，
避免源码时间戳触发隔离构建并请求 PyPI；
依赖或源码变化应重建质量镜像，不能通过放宽出网 ACL 修复依赖准备问题。

质量门的 `minio-quality` 使用固定 digest 的 GHCR 副本，其 manifest、配置及各层与已验收的
固定版 MinIO 的 linux/amd64 内容完全相同；不切换版本，也不在拉取失败时静默回退。
该副本只包含 linux/amd64；质量门主机须能够运行该平台的容器，不据此宣称其他架构资源验收通过。
生产与发布制品仍保留原上游多架构镜像引用。

本地完整质量门与 GitHub Full Gate 共用 `docker-compose.quality.yml`，不维护第二套
测试实现；本地、CI、Release 的完整编排统一调用 `scripts/run_quality_in_docker.ps1 -Stage Full`。
CI/Release 另保留 `always()` 回收以覆盖取消场景；仅当入口通过资源归属预检并输出
`cleanup_owned=true` 时执行，预检拒绝的旧资源不回收。不复制质量步骤。
当前 dev 处于快速开发模式，PR CI 只监听 `main`（见 RELEASE.md）；
所有指向 `main` 的 PR（包括 docs-only）及手动 dispatch 仍执行完整质量和安全门。
以下 Fast Gate / docs-only 分层规则只在恢复 dev PR CI 后生效：

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

当前 dev 分支不跑 PR CI（fast-development）；main PR 与 workflow_dispatch 仍执行完整
`container-gates`。单元测试的共享 SQLite client 夹具只证明功能路径；RLS、迁移和真实
并发必须由 `tests/integration` 的 PostgreSQL 套件证明（种子阶段用管理员角色建库/种数据，
测试主体再 `SET ROLE dramaforge_app`）。Worker 测试中注入 typed error 或 claim 是为了
隔离编排行为，不替代 PG 的 claim/RLS 语义。

当前前端 dev 工具链的 critical/high 已通过 vitest 5 / vite 补丁升级消除；剩余
moderate 项来自 minimatch/eslint/openapi 工具链，不进入生产 bundle。依赖审计结果只对
当次 lockfile 有效，任何依赖变化都必须重新核对，不能把一次审计当作长期结论。

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

完整脚本默认分配独立的 `df-quality-<随机标识>` Compose 项目与合同输出目录；
CI/Release 用 run ID 和 attempt 绑定项目。显式设置 `COMPOSE_PROJECT_NAME` 时必须
使用 `df-quality-` 前缀；项目已有容器（含停止状态）、网络或卷时拒绝运行，输出目录非空
也拒绝覆盖。结束时只回收本次创建的资源，不再在启动时清空旧质量栈。可通过
`QUALITY_CONTRACT_DIR` 指定本任务的空输出目录。镜像标签仍共享，因此完整构建不要并行。
Playwright 结果写入该目录的 `playwright-results/`，不随临时容器删除；CI/Release
仅在失败时上传已有结果，远端保留期服从仓库 artifact 设置。本地失败原件按上述生命周期保留。
普通 docs-only 改动不因新增验收文字就运行完整门。

## 本地离线安装验证

`scripts/verify_offline_install.ps1` 可在独立目录和 Compose project 中构建、打包并实际
运行 `install.ps1 -Offline`。例如使用 `-Port 8096 -WorkDir .\tmp\offline-install-check`。
它拒绝覆盖已有验证目录、容器或卷；请保留失败证据并为下一次验证使用新的目录和候选。
验证前须提交运行与打包目录中的全部构建输入；既有未跟踪清理文档不属于镜像输入。
`-SkipBuild` 只复用来源 SHA 与版本标签均匹配的本地候选镜像。包内包含完整的 LiteLLM
配置、网络策略与 bootstrap 文件，初始化任务须退出 0，常驻服务须全部健康。
这是本地候选安装验证，不代替版本化 Release、其实际制品的 online/offline 干净安装或
Owner 发布门禁；不会运行真实 Provider 生成。

## 运行健康检查与真实验收驱动的区别

`/health`、`/gateway-health` 和容器状态仅证明运行与来源信息，不能证明创作、Provider
或作品质量。不能将所有 `scripts/prove_*.py` 统称为“零成本 smoke”，也不能假设它们
都有 `--real` 或金额预算开关。以下是当前源码中的主要差异：

| 脚本 | 实际边界 | 使用要求 |
|---|---|---|
| [prove_formal_live_chain.py](../scripts/prove_formal_live_chain.py) | 有注册/创建工作空间、项目和 executions 写入；paid dispatch 需 `--real` 确认，无数字预算参数 | 注册/导入/预览不付费；`--real` 前先核对实例、身份、具体调用及逐操作授权 |
| [prove_professional_agnes_golden.py](../scripts/prove_professional_agnes_golden.py) | 创建并生成真实关键帧/视频；无 `--real` / 数字预算参数 | 是真实 Provider 驱动，不能以脚本名称代替预算/授权 |
| [prove_v1_r7_acceptance.py](../scripts/prove_v1_r7_acceptance.py) | 付费阶段有 `--real`/candidate 检查；preflight 无 Provider 调用但会写 profile、项目、绑定 | preflight 也需要明确的测试环境与写入范围；`--real` 不是 Owner 授权或费用上限 |

第三个脚本当前默认 base URL 是 8088，并非产品网关 8080；执行时必须核对并显式指定
已经安排的目标实例，不能只把端口改成当前可访问实例。脚本支持的参数以 argparse 为准，
不向没有该参数的脚本追加 `--real` 并声称安全。源码阅读可以发现边界，不代表脚本在新
候选上已验证；恢复与脱敏仍需在相应候选上用证据确认。

`prove_v1_r7_acceptance.py` 的 `--recovery-proof` / `--runtime-proof` / `--browser-proof`
是操作者提供的 JSON 证明。其中的 worker 停止/重启、Provider 操作计数和远端 ID 哈希
在仓库内没有程序化生产者，因此这些字段是**操作者证明（attestation）**，不是机器验证：
脚本会交叉核对 candidate、repair_run_id、entry_port、migration head 与项目身份，
但无法证明这些事件真的发生。它们只能作为发布评审的输入，不能单独充当发布授权或
“机器已验证”结论；需要强绑定时应另建带产生器与签名的证明合同。

`prove_v1_r7_acceptance.py` 的 delivery 阶段会独立调用本机 `ffprobe` 检查下载到的
Final Film 字节（视频+音频流、时长与渲染结果一致），不再只依赖渲染节点自报的 probe
字典；运行该阶段需要宿主安装 FFmpeg/ffprobe，缺失时脚本 fail-closed。

上述 proof 脚本与 live acceptance spec 默认使用一次性本地合成账号
（`professional-proof@example.com` 与合成口令），并支持
`DRAMAFORGE_PROOF_EMAIL` / `DRAMAFORGE_PROOF_PASSWORD` 覆盖。这些默认值只服务于
本地临时实例，不是可复用的生产凭据，也不得用于任何公开或共享实例；执行前应显式覆盖。

## 真实 Provider 证据（付费边界）

真实 Provider 证明需要当前任务的 Owner 明确授权（含允许创建的操作数；费用由供应商账户结算），且：

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

`workbench-resource.spec.ts` 在 1/30/100 镜头固定负载下记录首屏、请求、堆内存与缓存切换。
它由独立 `chromium-resource` Playwright 项目执行，普通 `chromium` 项目排除同一文件；
完整门仍覆盖全部场景，只隔离功能套件留下的浏览器进程状态，不修改浏览器版本、视口、
1→30→100 顺序、200ms 阈值或重试策略。单独验证可用现有 `test:e2e` 命令追加
`--project=chromium-resource`，不能以独立复测通过覆盖原始失败记录。
时间条有溢出时另验证真实横向滚轮可移动，并采样 30 次两端滚动到下一动画帧的耗时、
目标位置与实际位置；无溢出的单镜头记为不适用。滚动不得改变当前镜头，采样结果用于
建立该环境的基线，不冒称输入到屏幕呈现的完整延迟或真实后端性能。

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

文档整理只运行链接/锚点、目录、生成文档一致性与差异检查，不因此启动完整服务。
若网络故障期间在已有质量容器内安装当前锁文件并运行回归，必须明确记录源码、依赖、
执行范围与未完成的新镜像构建；这种分项结果不等同于 exact candidate 的正式完整门。

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

未发布开发实例统一使用 `dramaforge-dev` Compose 项目和当前源码构建镜像；
镜像、API、Workers 与 `DRAMAFORGE_SOURCE_COMMIT` 必须对应同一提交，不挂载其它 worktree
充当新实例。旧项目数据卷单独保管，不能自动合并或启动旧任务。
