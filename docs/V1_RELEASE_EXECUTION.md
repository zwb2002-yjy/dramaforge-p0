# DramaForge 第一版发布执行文档

> 本稿已由 [首版开发方案与实施计划](V1_DEVELOPMENT_PLAN.md) 替代。
> 原 W 编号与新开发任务的对照见合并方案，不同时执行两套计划。

状态：执行计划第一版，所有工作包尚未在本轮执行。  
日期：2026-09-15。分析基线：`dev` / `5ea45d6373d840d37f34a472b3dbe4853da9f8e6`。  
范围与验收合同：[设计文档](V1_RELEASE_DESIGN.md)。入口：[CURRENT.md](CURRENT.md)。

## 1. 执行原则与完成定义

按设计文档 AC-01 至 AC-10 完成发布闭环。先修确定性断裂和验收工具，再冻结候选，
最后申请具体付费操作与 Owner 发布处理。计划文档本身不构成这些操作的授权。
不得为了全绿降低测试期望、跳过正式门或把历史证据改成当前 SHA。

本轮完成的是文档编制及静态核对，不代表下表任何实施工作包已完成。
实施记录区分 `TODO / IN_PROGRESS / BLOCKED / VERIFIED`；VERIFIED 要附证据。
实际发布状态仍由 [V1_STATUS.md](V1_STATUS.md) 统一维护。

## 2. 工作包与依赖

| 顺序/ID | 工作包与主要落点 | 验证及退出条件 | 依赖/验收映射 |
|---|---|---|---|
| 0 / W0 | 候选准备：记录 HEAD、dirty 路径、当前部署/配置、证据可用性；核对审计结论 | 基线清单、实际复现结果；保留所有他人改动 | AC-09；本轮只完成文档所需静态核对 |
| 1 / W1 | 真实交付门：`backend/app/production/timeline_renderer.py`、`final_film.py`、`backend/tests/integration/test_timeline_render_ffmpeg.py` | 实际 ffmpeg/ffprobe 与解码测试进入质量容器；stub 不能满足正式证明 | W0；AC-07 |
| 2 / W2 | 提交与 UI 正确性：`frontend/src/features/director/api.ts`、`features/shots/ShotProductionActions.tsx`、`features/assets/AssetCardsPanel.tsx`、`routes/production-page.tsx` | 推荐命中真实路由；丢响应/双击保持原键；失败不报成功；状态来自真实节点 | W0；AC-03、06 |
| 3 / W3 | 审查准入：`backend/app/api/v1/review.py`、`execution/runtime_invariants.py`、`execution/shot_pipeline.py`、`production/formal_selection.py` 及实际入口 | 当前 Artifact 的人工决定可持久化；未审阻塞、审后可继续；无入口绕过 | W0；AC-03、04 |
| 4 / W4 | Repair 闭环：`backend/app/production/repair_service.py`、`api/v1/workbench.py`、`frontend/src/features/review/ReviewWorkspace.tsx` | 两种修复步骤、成本/预算、人工确认、回执及重开恢复；不隐式替换 Formal | W2、W3；AC-05、06 |
| 5 / W5 | 接通现有输入能力：`frontend/src/features/script/ScriptWorkspace.tsx`、`features/assets/`、`lib/api.ts`；复用 `api/v1/scripts.py`、`assets.py` | 浏览器导入支持格式、Artifact 入库与引用；刷新可恢复，错误/重复/越权受控 | W2；AC-02、03 |
| 6 / W6 | Director 发行配置：`backend/app/config.py`、`docker-compose.yml`、`.env.example`、bootstrap/installer 与部署说明 | API/worker 引擎一致；checkpoint 可用；AUTO 可达；MANUAL 不依赖导演 | W2；AC-01、09 |
| 7 / W7 | 执行边界及契约回归：本次修改跨层边、生成 OpenAPI、相关领域文档 | 无新增旁路、退休表面未恢复；审查/修复迁移单 head；已知架构债显式记录 | W1–W6；AC-03、09 |
| 8 / W8 | 免费全链及验收驱动加固：R7 驱动、live 浏览器规格、来源/证据校验 | 正反例、状态恢复、真实渲染、证据解析及逐操作预算控制就绪 | W1–W7；AC-01–08 的预演 |
| 9 / W9 | 冻结干净候选并执行全部正式容器/安全/迁移门 | 候选 SHA、版本、镜像身份、CI 均绑定一致；无失败或必需测试跳过 | W8；AC-09 |
| 10 / W10 | Owner 授权后的真实 Provider/LLM/浏览器验收 | AC-01–08 在候选上有真实证据，费用和未知提交可对账 | W9；逐操作正数预算授权 |
| 11 / W11 | 发行预演、Owner 合并、发布与安装验证 | AC-10 完成；实际 tag/Release/digest、备份恢复和平台证据齐全 | W9、W10；Owner 合并与发布处理 |

W1/W2/W3/W5/W6 可按依赖独立推进，但这不表示已获准派生代理或并发修改共享文件。
每个工作包完成实现和相关回归后再进入下一个依赖阶段，不按“写了代码”关闭任务。

## 3. 关键工作包操作细则

### W0：先校准事实

在仓库根目录读取 `git status --short`、`git rev-parse HEAD`，核对 CURRENT 与相关领域。
当前已有未提交文档和 `scripts/arch_import_scan.py`，不得顺手提交、删除或覆盖。
审计是快照；若代码已变化，先做最小复现，再修复或记录结论修正。
不自动继续 ARCHITECTURE_MAPPING 中的 Phase 2–7。

常规集成遵循 RELEASE 的 `dev` 流程。需要临时隔离时遵守项目分支规则：CI 对
`→ dev` PR 允许 `agent/*` 或 `dependabot/*`，不要套用不匹配的默认分支前缀。
本任务不要求创建或推送分支。正式验收另用已提交候选的干净 checkout。

### W1：让测试证明真实文件

1. 保留快速单测替身，为真实渲染用例显式选择真实路径，并处理 settings 缓存。
   不要只在外部设置 `APP_ENV=development`，测试 conftest 可能重新设为 test。
2. 在容器内生成确定性的短视频/音频/字幕夹具，通过实际编辑渲染服务生成成片。
3. 独立探测实际文件，检查 H.264、音频、时长、非空字幕、时间单调与媒体可解码。
   加入损坏媒体、`test_render` 产物不能通过正式证明的反例。
4. 接入现有 `backend/Dockerfile.quality` 的 integration 门；不得被静默 skip。
   CI 与 Release 工作流均须覆盖更新后的测试，继续使用锁定依赖和现有镜像工具。

### W2：请求身份必须先于自动重试

推荐完整路由应为 `/api/v1/projects/{project_id}/shots/{shot_id}/recommendation`。
修正前端测试中被固化的错误地址，增加与真实 OpenAPI/路由一致的检查。
同一次生产操作保持幂等键并接通执行回执读取；请求失败先区分明确失败与未知提交。
前端按钮禁用只是辅助，后端幂等/并发约束必须有 PG 验证。

对回收/恢复、保存和导出仅在服务端成功后显示成功。生产进度按 NodeRun 实际状态展示；
补全 `completed_after_cancel` 等当前有效状态，不用百分比推算每个节点状态。

### W3–W4：避免把审查接成死锁

先设计持久化的人工决定与素材身份关系，再接生产准入，再接 UI。
验证 `needs_human → 用户审查 → 当前素材可继续`，同时验证拒绝、过期、越权、
缺失审查、旧 Artifact 决定不能放行新 Artifact。覆盖实际 workbench、AUTO、Repair
和 FinalFilm 路径；不能只测试 `runtime_invariants.py` 的孤立函数。

Repair 计划与执行之间校验 Shot/素材版本；需要的 API 字段先更新 schema 和生成类型。
两阶段修复在关键帧返回后停在待人工确认，确认后再提交视频；刷新后恢复同一操作，
拒绝候选保持旧 Formal。补充重跑范围、保留素材和预算说明，不伪造确定性报价。

如需要迁移，先检查现有决定/审计记录可否复用；新增最小关联和约束，验证 RLS、
新库迁移与当前 head 升级。禁止通过手写数据库记录替代用户门的验收。

### W6–W8：先预演再付费

核对 langgraph 配置在 API 与 worker 上生效，迁移/角色/checkpoint 数据库连接可用，
记录启动失败时的明确阻塞。不要只改默认字符串后宣布 AUTO 可用。

复用 R7 脚本的 checkpoint 和原键回执语义，检查每个 phase 实际会提交哪些请求。
现有 `--real` 是允许真实调用的开关，不是金额上限或逐操作 Owner 授权机制。
若一个 phase 会发起多个未经逐项授权的付费操作，应先拆分或增加执行前控制，
再进入 W10；先完成代码、免费验证和费用清单，向 Owner 展示可审阅的具体操作。

扩充 live 规格覆盖本次新增的导入、资产、Review/Repair、超时回执、人工门及剪辑重导出。
现有 R7 浏览器规格只是复用起点，不能因文件存在便认定上述场景已覆盖。

## 4. 命令来源与正式门

命令权威为 [frontend/package.json](../frontend/package.json)、
[backend/pyproject.toml](../backend/pyproject.toml)、[CI](../.github/workflows/ci.yml)、
[质量 Compose](../docker-compose.quality.yml) 及其 Dockerfile。
下面是实施阶段的使用说明；本轮没有执行这些产品门。

### 4.1 本地正式容器质量门

仓库根目录，先确认只会操作本任务质量环境。现有脚本开头和结尾会执行
`down --volumes --remove-orphans`，共享机器须设置专属 Compose project，不能触碰其他
会话容器或正式数据卷。独立 checkout 隔离脚本固定的 `tmp/quality-contract` 输出。

```powershell
$env:COMPOSE_PROJECT_NAME = "dramaforge-v1-release-quality"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1
if ($LASTEXITCODE -ne 0) { throw "容器质量门失败" }
```

名称须确认未被其他任务使用；结束后恢复此前环境变量值。质量门覆盖后端静态检查、
单元测试、真实 PostgreSQL 集成、迁移、OpenAPI、前端格式/lint/typecheck/test/build、
mock browser E2E 和 pinned LiteLLM 代理集成。W1 要确保真实渲染测试加入其中。
这份本地报告不能替代远端 `policy`、`container-gates` 和 Security workflow 结果。

安全检查继续按 [security.yml](../.github/workflows/security.yml) 执行 secret、
Python/npm 依赖和 Trivy 扫描；Dependency Review 仅按现有能力开关处理。
不要通过主机安装依赖、少跑 PG 测试或忽略 integration skip 来替代容器门。

### 4.2 R7 验收驱动参数核对

实际脚本：[prove_v1_r7_acceptance.py](../scripts/prove_v1_r7_acceptance.py)。
`--state` 必需，`--phase` 默认为 `preflight`；只加 `--real --candidate` 不会自动执行全链。
其默认 base URL 为 `8088/api/v1`，正式入口应显式设置为所验收的 8080 网关。

以下仅为容器内调用参数模板，`<...>` 必须替换；运行容器须具备仓库脚本、锁定 Python
依赖、证据挂载和网关网络连通性。用户名/口令依当前脚本登录约定从私有环境注入。

```text
python /workspace/scripts/prove_v1_r7_acceptance.py \
  --state /workspace/tmp/p0-evidence/<candidate-sha>/formal/r7-state.json \
  --base-url <reachable-gateway-origin>/api/v1 \
  --phase preflight \
  --evidence-dir /workspace/tmp/p0-evidence/<candidate-sha>/formal
```

当前可选 phase 包括 `story`、`media`、`review-submit`、`review-collect`、`editing`、
`regressions`、`delivery`、`collect`，另有恢复/替换/候选提升阶段。
W8 必须按源码与前置状态形成逐 phase 操作清单，不盲跑全部恢复/替换分支。
付费阶段只有拿到具体授权后才增加 `--real --candidate <40位SHA>`；每一步完成后
校验 state 和回执再继续，失败/未知不新建 state 绕过 checkpoint。

### 4.3 真实浏览器与来源证明

复用 [playwright.r7.config.ts](../frontend/playwright.r7.config.ts)，通过项目已安装
Playwright 运行；在同候选的前端工具容器中、`frontend` 工作目录执行：

```text
npm exec -- playwright test --config=playwright.r7.config.ts
```

配置真实可达的 `DRAMAFORGE_R7_BROWSER_BASE_URL`，并准备现有规格要求的 8 项变量：
`DRAMAFORGE_R7_CANDIDATE_SHA`、`DRAMAFORGE_R7_ENTRY_PORT`、
`DRAMAFORGE_R7_WORKSPACE_ID`、`DRAMAFORGE_R7_TEMPLATE_PROJECT_ID`、
`DRAMAFORGE_R7_FREE_PROJECT_ID`、`DRAMAFORGE_R7_TEMPLATE_EDIT_SESSION_ID`、
`DRAMAFORGE_R7_FREE_EDIT_SESSION_ID`、`DRAMAFORGE_R7_BROWSER_PROOF`。
ID 必须来自本次实际资源，不得复用不存在的历史 ID；环境映射与登录准备在 W8 预演。

live 验收不拦截业务 API 返回假成功。主要记录 DOM、API、网络、console、布局、
业务流断言和服务来源；截图遵守 AGENTS 的尺寸、哈希与按需查看规则。

## 5. 候选与证据管理

W9 前完成实现、测试、迁移、版本和相关文档修订，提交后冻结候选 C。
干净树意味着不存在会使来源校验失败的已跟踪修改或未跟踪源码；用隔离 checkout
获得干净来源，不删除其他人的文件。正式证据必须符合 `scripts/evidence_context.py`：
`source_commit == ending_source_commit == C`、`dirty == ending_dirty == false`、
`source_consistent == true`。运行中修改源码会使证据失效。

为每次候选准备下列证据清单，字段是本计划要求的记录格式，不宣称已有统一生成器：

| 记录 | 必含信息 |
|---|---|
| 来源 | C、起止 dirty 状态、版本、迁移 head、镜像 digest、配置摘要（脱敏） |
| 验收 | AC ID、命令/场景、时间、结果、退出码、CI URL 或制品 URI |
| 运行关系 | Project/Shot/EditSession、NodeRun、ProviderOperation、Artifact、Formal、timeline 版本 |
| 费用 | Owner 授权记录、操作/阶段、Provider/模型、币种、正数上限、实际或未知费用、回执 |
| 媒体 | MP4/SRT 路径、字节数、SHA-256、独立 ffprobe/解码、人工复核结论 |
| 发行 | 合并记录、最终 tag SHA、包与镜像 digest、安装平台、恢复验证结果 |

保存为可严格解析的独立 JSON/日志，不能把多段 JSON 拼接后仅搜索 `complete: true`。
`tmp/` 被忽略不代表长期保存；发布前将脱敏证据归档到可持续访问的制品存储，
索引记录校验哈希。V1_STATUS 只引用真实收据，不把二进制加入仓库。

任何候选变更生成新证据目录。若合并或仅文档提交使最终 SHA 改变，必须显式区分
验收 C 与发行 R，并按现有候选等价证明机制校验全部声明复用的路径、依赖、迁移和配置。
不能证明等价则重新验收受影响部分；最终发行 SHA 上仍需完整质量门和发行 smoke。
不手工改旧报告 SHA，不因避免重付费而伪造等价。

## 6. W10 真实验收清单

- [ ] 每个付费 probe/生产/repair 操作有本次 Owner 正数预算授权，文本成本也纳入核算。
- [ ] 所有服务与镜像身份匹配 C，APP_ENV 不是 test，账户/模型能力实际可用。
- [ ] Template + AUTO、Free + ASSIST 两条初始化组合走同一主链，实际导出 15–30 秒成片。
- [ ] MANUAL 在导演 worker 停止时走通；停服务只作用于本任务隔离环境。
- [ ] 从浏览器完成剧本导入、生成结果转资产、镜头引用和上下文恢复。
- [ ] 未审素材受阻、人工决定可追溯；Repair 两选项及关键帧/视频中间门均完成。
- [ ] 重复请求和丢响应通过受控故障注入验证；未知提交先查回执，无盲重试。
- [ ] 编辑后 Save/Export 绑定版本，零新增媒体 Provider 调用，生产真相不变。
- [ ] 下载实际 MP4/SRT，独立检测和解码，人工确认对白、字幕、叙事和视觉质量。
- [ ] AC-01–09 证据齐全，严格解析、身份校验与哈希检查通过。

授权不足时只暂停依赖该操作的付费步骤，其余免费工作继续；不把 BLOCKED 写成 PASS。

## 7. W11 发布、安装与恢复

1. **候选预演。** 从同一 C 构建发布镜像，按 `docker-compose.build.yml` 与
   `docker-compose.yml` 启动独立实例；验证 `/gateway-health`、`/health`、worker、
   checkpoint 和 source identity。只发布网关端口，不额外暴露 API/数据库。
2. **交付 Owner。** 准备 `dev → main` PR 的具体变更说明、AC 结果、风险、版本、
   证据索引与发行说明；核对远端实际 checks/ruleset，不把历史 PR #66 当成本次状态。
   仅 `@zwb2002-yjy` 批准和合并；Agent 不写 MERGED。
3. **核对最终来源。** Owner 合并前审阅最终提交标题、正文、作者与 attribution trailers，
   合并后核验实际远端提交。若发行 R 不等于 C，按第 5 节处理等价与重新验收。
4. **发行版本。** 核对仓库全部版本声明与 `scripts/release_contract.py`；最终 tag 为
   对应版本的 `v<SemVer>`，落在受保护发布流程的来源上。tag 推送会触发
   [Release workflow](../.github/workflows/release.yml)，属于实际发布动作。
   当前 workflow 还支持手动和 dev 候选触发，它们不能代替 Owner 的稳定发布决策。
5. **检查制品。** 工作流成功后核对真实 Release、镜像 digest、在线/离线安装包、
   checksum、SBOM/工作流产生的证明；文件缺失或来源不一致就保持未发布完成。
6. **安装验收。** 从实际发行包在干净目标实例运行 `install.ps1` 或 `install.sh`，
   验证首次 Owner 创建、登录、模型配置、创建项目、媒体访问与重启恢复。
   对外声明的 OS/CPU/在线或离线安装组合均需对应实测；未测不宣称已支持验证。
7. **升级与恢复。** 备份原 `.env` 和持久卷；用 maintenance 的 backup/restore-verify
   在隔离目标检查数据库与对象恢复，并验证密钥不被替换、已有凭据/Artifact 可读。
   若没有既有部署，至少完成新实例备份恢复演练，升级路径标记未实测。
8. **最终记录。** 在 V1_STATUS 记录 R/tag/日期、证据 URI、实际平台/模型、遗留限制、
   Owner 发布结果；AC-10 及其余 AC 全部通过后才标记发布完成。

回退时停止本次环境的新提交，先对账进行中/未知付费操作。保留证据与当前数据快照；
只有确认数据库兼容时才切回上一镜像 digest，否则先在隔离环境验证备份恢复方案。
首次发行没有“上一稳定版”时保留实例并修复/重发候选，不承诺不存在的自动回滚。
正式环境不使用 `down --volumes`，不盲跑 Alembic downgrade，不删除原数据卷。

## 8. 执行记录模板与本轮交付状态

每完成一个工作包填写：`工作包 ID / 实际提交 / 修改路径 / 验证命令 / 结果 / 证据 URI /
已知限制 / 后续依赖`。每次收费步骤另外填写授权与回执，未知金额保留 unknown。

本轮：两份文档已编制；业务实现、正式质量门、真实 Provider 验收、远端合并/tag、
生产部署均未执行。下一实施起点是 W0/W1，而不是直接运行真实验收或发布流程。
