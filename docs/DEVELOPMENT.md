# DEVELOPMENT — 开发与测试权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

## 原则

运行时、依赖安装、静态检查、测试和 E2E 统一在 Docker 中执行；宿主机不创建
Python venv、不安装 Node 依赖，也不直接启动 API 或 Vite。
Git、PowerShell 和容器编排脚本自身的隔离测试可使用宿主原生工具；它们不安装应用依赖，
不启动宿主 API/Vite，不替代容器中的产品测试。

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

一次任务按“完成一个连贯修改批次 → 相关测试 → 修复失败 → 受影响回归 → 合同要求的完整门”推进。
不在每次保存、删除一个文件或整理一条断言后机械启动验证；诊断失败需要快速反馈时可提前跑
该失败用例。已通过检查仅在其覆盖的源码、依赖、环境变化或存在未解决疑点时重跑。
无关文档、报告文字、提交消息变化不使产品测试结果自动失效；新 SHA 不等于所有行为都变化。
复用结果须说明已测输入与当前差异，不能把不同输入的局部结果拼成当前候选完整验收。
文档改动检查差异、相关链接与合同；高风险变更和发布的完整门要求仍有效。
最终报告给出改动范围、源码/工作区状态、实际命令及结果、未运行项和剩余决策即可。
修改历史由 Git 保存，日常结果记在对话中；不要每轮新增日期命名的测试、审计或计划文件。

| 本地修改范围 | 批次完成时的验证 | 升级条件 |
|---|---|---|
| 只读审计 | 引用当前源码与调用者，不启动测试或服务 | 有实际修改后重新判断 |
| 文档澄清、链接、普通措辞 | 差异、相关链接/锚点；涉及可执行合同则跑该合同测试 | 真正改变架构原则/安全或正式发布要求时升级 |
| 单域 Unit/fixture 去重 | 保留用例及共享 fixture 的受影响消费者；确认保留用例没有意外漏收集 | 删除独立风险覆盖不可接受；涉及 PG/E2E fixture 时补对应回归 |
| 单域实现、API/Runtime 局部修复 | 相关行为测试、静态检查及实际调用方回归；公开 schema 变化补生成客户端检查，数据库行为补 PG | 按真实依赖扩展验证，不因目录名、文件类型或同时修改前后端自动 Full |
| 质量脚本、检查器、构建/CI 配置 | 验证接受/拒绝、失败传播、资源归属与真实配置解析；构建输入变化验证受影响镜像，测试选择变化核对收集范围 | 只有无法通过受影响阶段可靠覆盖的跨栈执行、隔离或构建链变化才升级 Full，并说明具体风险 |
| 跨栈迁移、权限/身份/恢复的系统性变化，或无法可靠界定影响的行为变化 | 定向诊断后，由协调者对冻结候选执行 Full | Full 是这些风险和正式 CI/发布要求的验收方式，不是所有开发切片的默认结尾 |
| 已授权可再生临时产物删除 | 路径/归属/引用检查、删除结果与保留项核对 | 没有源码变化，不因此重跑产品全量测试 |

此表选择本地反馈，不削减 main PR、手动 Full 或发布必需检查。多项变化取最高实际风险；
不能确定影响时先查调用链，仍无法可靠分类的行为变更升级 Full。通过阶段只有输入或依赖
确实变化时才重跑；不因补写文档、新提交 SHA 或修正无关阶段而全部重来。正式候选需要
完整门时仍执行未过滤的 Full，不把分项复用报告成一次完整门。宪法文字澄清不自动等于
改变架构原则；是否改变允许行为、身份、安全或执行路径是判断依据。

### 提交点与阶段终点

连贯批次收口后立即提交到 `dev`，不把多个批次累积成一个工作区：代码、测试、权威文档与
定向证据同批落地，提交消息说明本批范围与证据编号。未提交成果越大，回滚、定位和交接成本
越高，一次误操作会连带毁掉此前全部已验证批次；提交前核对没有其他会话的在途改动。本轮
时间不足时按“保留已验证与在途改动，写清已做/已测/待测/下一步”交接，不回滚重做。

按上表选择开发期验证。同一用户流程内，先验证后续工作依赖的公共接口，再连续开发并集中运行相关用例、做代码 Review、修复及受影响回归。阶段或切片编号本身不触发 Full。系统性高风险或无法可靠限定影响时按上表执行 Full，并在现有执行状态记下具体风险。正式 CI、发布和 I10 最终候选执行各自要求的完整门。

启动交付候选的 Full 前，按现有验收项确认正常入口至最后一个实际消费者已连通、必需调用方已接入、已知阻塞已处理。失败先定向复现和修复，再按同一候选的正式要求验证。多个局部结果不能拼接为 Full。

业务流程从正常入口在试用环境以样例走通后，即可交付入口、样例、预期结果和当前限制，继续后续工作。机制验证、用户试用和合同最终验收分别依据各自证据记录。

长门用短轮询：单次等待不超过约 10 分钟，轮询间隙做下一片的只读准备，避免整轮时间花在
阻塞等待上。门失败先定位根因，集中修复后只复跑受影响阶段，再按验收要求验证最终候选。

### 测试资产的增删条件

测试用于保护独立行为与风险，不用于保存“曾经改过”的记录。清理开始先在对话中给出
本批次非显然删合决策的风险与保留覆盖，不要求逐文件、逐断言台账；普通临时产物删除
只核对范围和使用状态，不套用代码覆盖审计。
仅发现现有测试没有覆盖的可观察风险时新增或扩展测试；优先修改现有用例，不为每条文案、
每个删除文件或每轮修复新建测试文件、快照、fixture、包装脚本或治理自检。
重复断言可合并/参数化，但不能删掉不同角色、拒绝路径、事务、并发、恢复或未知提交场景。
Unit、PG Integration 与 E2E 即使操作相似，也可能保护不同风险，不能仅按名称或行数去重。
断言业务结果与副作用，避免仅镜像实现、绑定函数名/文件排版或让测试证明自己的配置。
新增保护说明独立风险；删合保护说明保留位置。测试数量、文件数量均不作为完成指标。

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

只因“曾经测试过、失败过、付费过或叫正式证据”不构成永久保留理由。
保留须服务于当前调试、当前候选验收、仍需恢复的业务或明确的交付/归档要求；
用途结束后清理。截图原件不得在使用中改写，但并不因此永久存档。

| 对象 | 保留边界与收尾 |
|---|---|
| 日常修改记录 | Git 保存代码变更，对话给出本批结果；不额外生成逐次修改台账、日期报告、源码快照或清理证明文件 |
| 普通成功测试输出 | 消费完即清理本次日志副本、截图、trace、JSON/HTML 报告和中间合同文件；不只限于定向测试，普通本地 Full 同样适用 |
| 失败诊断 | 只保留当前仍需排查的最小复现材料；问题解决或该任务/旧环境已明确废弃后清理，不要求为已废弃环境重新复现成功才能删除 |
| 正式候选证据 | 仅在该候选仍待评审、仍被有效发布引用或被明确要求归档时保留；废弃候选可整批清理，并停止引用其通过结论，不为每次开发构建建立正式证据包 |
| 旧实例数据、备份、真实生成样本 | 属于已明确弃用且无恢复/交付需要的旧环境时，列入一次历史清理批次；不默认先复制到另一处或重新压缩归档。当前作品、活跃数据库和对象存储另行处理 |
| 可能已计费或未知提交 | 有待核对/恢复需求时保留必要操作身份与回执，不能重提交；删除旧环境材料不撤销远端任务、不退费，也不授权新 Create。确需保留的最小事实不要求保留整个验收目录 |
| 测试源码、fixture、迁移 | 是当前可执行合同或构建输入，不是执行流水；按消费者和独立风险删合，不能因环境重置一起清空 |
| 当前构建缓存、镜像、worktree | 按使用状态和重建成本回收；未提交修改、未集成提交或归属不明时不删除，不终止其他会话 |

跨任务清理使用一份精确批次范围（在对话或用户要求的单份方案中即可），获 Owner 授权
后按范围执行，不逐文件重复请示、不新增清理账本。只保留确有用途的例外并说明结束条件；
历史失败、原始截图、备份或旧付费样本不再是整类永久豁免。
环境重置可以终止旧候选用途，但不能凭目录日期推定新环境数据也已弃用。

临时输出只进任务自己的 gitignored `tmp/`；运行中保持隔离，收尾删除可丢弃输出，
不覆盖另一个会话目录。优先复用 Docker 构建缓存，不复制 node_modules、完整源码和镜像包。
没有单独的永久本地审计档案要求，也不自动触发真实 Provider 调用来补被清理的历史证明。
Full 入口的自动收尾范围见下文；其他专项输出仍由任务收尾，不宣称已经实现全仓 TTL。

### 专项 Agent 合同与集成

主 Agent 独占 CURRENT、架构权威、baseline、共享 CI/Compose 和最终验收；专项 Agent
按明确目录/文件拥有写权，不能同时修改同一权威。在现有对话明确目标、可写范围、
不可变边界、验收与回滚边界即可，不另建 Task Contract 或任务状态机；未授权文件只提交建议。
只读审计先列真实消费者、职责、替代影响和验证成本；再决定 KEEP/收敛/Owner 决策。
LangGraph、生产事实链、用户门、执行身份和付费授权不是依赖精简的可选项。

专项执行聚焦回归，主 Agent 在整合后的当前源码上统一运行受影响门及必要完整门。
可并行只读审计；有写权的批次必须明确文件清单，共享 fixture 由一个负责人修改。
同一整合候选的 Full 由一个协调者运行，各 Agent 不各跑一遍；全部修改须冻结后才开始。
若 Full 失败，先复现/修复受影响阶段，再按合同验证新候选；不得把旧失败改成通过或盲目重跑。
提交前核对其他会话改动；回滚只还原本切片代码，不删除历史事实、证据或数据卷。
ARCHITECTURE_MAPPING 只记录长期架构决策、真实结构债务及已授权目标；临时跨模块修复、
分工与进度留在现有对话，不追加到架构文档。结果在对话/既有证据中报告，完成后不保留
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
宿主 Python 仅用标准库编排 Docker，不提供应用测试依赖。运行中使用新的 `tmp/` 目录；
成功默认删除本次备份与输出，只打印摘要，失败保留诊断。正式留档显式传 `--keep-artifacts`。

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
当前没有独立 Backend Fast / Frontend Fast 或汇总 Required Check 作业；定向容器模式
是本地反馈入口。恢复 dev PR CI 须另行决定并同步 workflow、测试、RELEASE 与 Ruleset，
不把历史方案中的路径分层视为已实现或自动生效。main 的必需检查名称只在 RELEASE 维护。

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
受限网络下构建前端镜像可传 `NPM_REGISTRY` 构建参数指向内网/区域镜像；默认仍是公共
`registry.npmjs.org`，因此提交的 lockfile 保持可移植。

运行时基线为 Node 24.x、Python 3.14.x；Docker 标签允许系列内维护更新，
不是不可变的补丁版本 / digest 锁定。Dependabot 的常规版本更新先进入 `dev`，
Node 跨主版本、Python 跨次版本升级由独立任务评估。安全更新仍依 GitHub
默认分支机制处理；本地版本选择文件位于 `frontend/.nvmrc` 和
`backend/.python-version`。

完整脚本默认分配独立的 `df-quality-<随机标识>` Compose 项目与合同输出目录；
CI/Release 用 run ID 和 attempt 绑定项目。显式设置 `COMPOSE_PROJECT_NAME` 时必须
使用 `df-quality-` 前缀；项目已有容器（含停止状态）、网络或卷时拒绝运行，输出目录非空
也拒绝覆盖。结束时只回收本次创建的资源，不再在启动时清空旧质量栈。可通过
`QUALITY_CONTRACT_DIR` 指定本任务的空输出目录。前后端质量镜像分别固定为
`dramaforge-backend-quality:local`、`dramaforge-frontend-quality:local`，不随 Compose 项目名
生成新镜像标签。Full 构建通过 `--iidfile` 捕获各自的不可变 ID，所有后续 Compose 服务
通过 `QUALITY_BACKEND_IMAGE` / `QUALITY_FRONTEND_IMAGE` 使用本次 ID；共享标签被其他构建
覆盖也不会切换执行源码。不同运行仍必须使用独立项目和输出目录；不要对活跃任务做全局 prune。
Playwright 结果写入该目录的 `playwright-results/`。普通 Full 在全部检查及容器回收成功后，
自动删除本次独占且位于仓库 `tmp/` 内的输出目录；两个固定质量镜像保留，供后续构建与
发布步骤复用，不再逐次创建并删除项目镜像。固定标签不等于 Docker 层缓存自动清空，
也不授权清除其他任务的旧镜像或全局 prune。
失败、中断和容器回收失败保留输出与镜像。已有非空目录仍拒绝覆盖；外部路径不自动删除，
目录归属变化或内部链接使清理失败并保留材料。正式候选需要保留成功输出时显式传
`-Stage Full -KeepArtifacts`；Release workflow 使用此开关。
CI/Release 仅在失败时上传已有结果，普通失败证据在远端保留 7 天（workflow `retention-days: 7`）；
正式发布制品按发布流程另行管理。
本地失败原件及显式保留的候选输出按上述生命周期收尾，不自动回收其他任务目录。
普通 docs-only 改动不因新增验收文字就运行完整门。

## 本地离线安装验证

`scripts/verify_offline_install.ps1` 可在独立目录和 Compose project 中构建、打包并实际
运行 `install.ps1 -Offline`。例如使用 `-Port 8096 -WorkDir .\tmp\offline-install-check`。
它拒绝覆盖已有验证目录、容器或卷；只允许仓库 tmp 内的独立输出目录。结束时回收本次
安装栈；成功默认删除安装包、转储和输出，失败保留诊断。正式留档显式传 `-KeepArtifacts`。
验证前须提交运行与打包目录中的构建输入；文档和外层验证脚本修改不强制制造产品提交。
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

开发切片按本页风险表执行受影响回归；Provider/API/Worker 等路径名或前后端联合修改
本身不触发本地 Full。main PR、手动 Full 和发布仍执行既定完整门。离线测试与 CI 门不得真实调用外部模型；mock 只覆盖协议与
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

仅对本任务明确纳入的 AC，在现有对话中记录通过/失败/未运行及必要证据位置；正式合同整体验收才逐项核对全部适用 AC，不为普通切片建立全量 AC 台账。技术错误、交互阻断和作品判断分开：
FFmpeg 解码成功不证明叙事成立，人工喜欢画面不放行重复扣费或身份错误。作品评审缺少
预算、真实素材或 Owner 判断时保留未验收状态；不通过改写初始创作目标获得通过。

证据写入任务自己的 gitignored `tmp/`，最终候选证据再按既有发布路径管理。在有效保留期内保留原截图，
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
python scripts/maintenance_cold_backup.py --project <project> --compose-file <compose-file> \
  --repository <local-dir> --staging-parent <local-staging-dir> --password-file <local-secret> --report <new-receipt>
docker compose --profile maintenance run --rm maintenance restore-verify \
  --repository <mounted-repository> --snapshot <full-id> --password-file <mounted-secret> \
  --receipt <mounted-receipt> --target-config <mounted-config> --staging <new-directory>
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
充当新实例。旧项目数据卷不能自动合并或启动旧任务；需要恢复时单独保管，已明确弃用的
环境按上述历史批次清理，不默认永久保管。

## 机构版验证合同（D7设计，待实施）

需求逐项与测试文件映射维护在[TEST_EVIDENCE](implementation/TEST_EVIDENCE.md)的D7矩阵；
该矩阵是拟实施验收，不是通过记录。原型DOM通过、单测通过、真实PG通过、Full Gate、真实作品与目标机验收分开。
下面命令记录D7核对的真实现有入口，不将命令定义当执行证据；D8后按主合同/N11及当时范围实际运行。

### 已核对的执行入口

来源：frontend/package.json、backend/pyproject.toml、两个Dockerfile.quality、docker-compose.quality.yml、
scripts/run_quality_in_docker.ps1和当前工作区CI。脚本只支持Full/BackendTests/FrontendTests三个Stage，
BackendTests/FrontendTests构建当前源码镜像并以固定image ID、network none运行；没有PG依赖，不能用它们执行PG验收。

```powershell
# 范围内后端单测；这里列出的是当前真实存在的回归文件。
.\scripts\run_quality_in_docker.ps1 -Stage BackendTests -TestArgs @('tests/unit/test_project_files.py', 'tests/unit/test_source_parser.py', '-q')
# 前端逻辑/交互单测；不等于浏览器或真实API验收。
.\scripts\run_quality_in_docker.ps1 -Stage FrontendTests
# 同一候选完整门，不允许TestArgs过滤。
.\scripts\run_quality_in_docker.ps1 -Stage Full
```

集成/媒体/浏览器回归沿Full的同一quality Compose网络和现有编排：backend-quality在真实PG上upgrade/check与integration，
frontend-quality从该后端导出OpenAPI检查生成类型并执行真实生产build/routes/Playwright；media-resource-quality等服务
承载FFmpeg/媒体及隔离网络合同。目标新测试放入对应现有发现目录，不能另建一个弱化的“机构版Full”。
普通切片若只需一次PG反馈，可由协调者在自己已确认拥有的隔离quality栈复用同一backend质量镜像/环境执行精确pytest文件；
必须记录该真实Compose project和镜像ID，不能用BackendTests的network none冒充PG，不能临时连宿主/业务实例。
未创建隔离栈时不写一个假定存在项目名的命令；触发完整门时执行同一候选的无过滤 Full。

backend Dockerfile当前Full包含ruff/mypy/unit、alembic upgrade head/check、带--fail-on-skip的integration，
另由quality编排执行Proxy/媒体/网关合同；源码中对某些Proxy测试的ignore对应后续专用服务，不是可随意增加跳过项。
前端build已经包含typecheck，除定位失败无需额外重复；generated.ts由后端真实OpenAPI生成，不手写DTO或改期望适配缺陷。
CI当前文件调用同一-Stage Full；工作区CI本身有原未提交修改，不能据本地文件声称远端CI已执行或规则已生效。

### 测试数据与证据级别

- unit：纯领域输入、Fake/MockTransport和真实受理/编译代码，断言业务结果、错误与副作用计数，避免只匹配源代码字符串。
- PG：独立临时库、真实Alembic/触发器/组合FK/GRANT/FORCE RLS，运行角色非owner、NOBYPASSRLS；
  admin只建fixture和核对不可见事实，受测调用不能借admin session绕过权限。
- processor/media：固定合成PDF/DOCX/TXT/扫描图/音视频/CSV/XLSX，实际运行锁定处理器/FFmpeg并核验定位/hash/时长，
  不能把stub OCR/ASR返回字符串称全格式通过。离线模型/二进制缺失是未通过，正式门不可skip。
- 浏览器：固定API fixture验证交互边界；另有连接真实隔离API/PG/对象存储/Workers的机构旅程，按N08/N10三栏结构，
  两种证据分别命名，不能用professional-mocks代替真实受理/持久恢复。
- 上游：默认所有quality新调用都去受限计数Mock服务，拒绝路径断言0，未知提交断言Create累计仍1；
  真实Provider与真实机构资料均有独立Owner授权及明确操作上限，没有授权不执行，也不以mock填通过。
- 目标机：Windows/WSL2现有Docker方式、浏览器、服务重启、restic/多库恢复与真实保护集另测，
  Linux CI及原型localhost服务不能代替此层。媒体可解码与文化/叙事/视觉质量评审分别给结论。

固定fixture包含两个用户、同用户两个Workspace、至少三个项目、连续剧两集、重复/更新/解除关联资料、
来源许可撤销、同名不同身份人物、共享资产固定版本、已保存草稿、known remote和unknown_submission。
过程记录预期输出、模型请求计数、持久ID/版本及安全事件；不把真实原件/Key/base64装进测试报告。
故障注入以确定屏障控制发送前/准入后/远端受理后/落库前/Outbox发送前后；不靠随机sleep假装覆盖竞态。
恢复测试不得通过删失败任务、改status、清unknown标记或重建幂等键获得绿色结果。

### 最终候选与禁止降级

局部反馈可以针对未提交工作区，但记录dirty与实际镜像ID；不能伪称等于干净HEAD。
最终可审计证据沿现有evidence_context校验：起止SHA相同且clean，容器由该候选及锁定依赖构建。
既有dirty需先审查整合，不reset/覆盖；若尚未形成干净候选就明确最终证据未成立，不关闭I10。
通过后的检查只在受影响源码/依赖/环境变化或未决问题时重跑；D8文档冻结不触发付费测试。
任一必须的权限/迁移/恢复/三作品/部署/Full项缺失都保留未完成，不通过删用例或降低断言换PASS。

### 真实机构旅程接入现有Full（I0接线已写入，运行待验证）

已读取当前Playwright global-setup和vite.config：它们用进程内Vite及DRAMAFORGE_E2E_API_URL代理，
现有director-agent/editing-deliverables等用例使用professional-mocks，不能证明真实API/PG/Worker持久闭环。
已新增`frontend/tests/institution/`与`playwright.institution.config.ts`，
复用现有global-setup和浏览器启动设置，testDir与现有mock套件分开。测试不拦截业务API制造成功，不使用test.skip。
通过现有npm脚本传`--config playwright.institution.config.ts`；配置拒绝非隔离API地址。当前容器尚未运行，不能声称浏览器套件通过。

已在原docker-compose.quality.yml与Full协调脚本中增加同候选的隔离fixture服务：
institution-api-quality、institution-dispatcher-quality、institution-worker-default/director/heavy-quality、
institution-upstream-quality、institution-browser-quality。它们复用业务镜像/入口，不是新产品Runtime，
仅在本次独占df-quality-*项目运行；与当前postgres/redis/minio-quality及计数Mock服务组成内部网络。
所有业务URL/密钥/数据库/桶均显式合成配置，不继承本地.env中的真实Provider信息，不挂载Docker socket。
真实业务测试进程只连internal网络，模型流量仅准入计数Mock，不能走互联网fallback。
新测试库/桶与其他quality测试隔离，Redis使用独立DB14；institution-bootstrap-quality只接受固定合成目标、拒绝已有同名库，
执行迁移并核对app/checkpoint角色不绕过RLS。清理由Full现有资源所有权检查负责，不能用于现有实例。

Full在原检查之外启动这组服务、等待真实ready、执行机构浏览器套件并收集退出码，任何失败使同一次Full失败。
不是拼接另一次窄测试的成功报告；CI仍调用同一-Stage Full，不另加弱化工作流。
这一层验证真实API/PG/对象存储/Worker与浏览器状态，使用合成媒体与Mock上游；
Vite代理不是部署后Nginx验收，已有Nginx合同与I10正式镜像/目标机检查仍保留。

I0首条baseline用例覆盖真实注册/项目/合成TXT上传、dispatcher解析、来源内容读回、浏览器刷新持久性、
跨用户拒绝与Mock上游零调用。尚未覆盖新机构能力或三作品完整旅程；后续各批直接扩展此套件。
当前Worker健康沿用队列心跳，只是新隔离队列中的启动检查，不冒充目标中的每进程维护mode/readiness。
