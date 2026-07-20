# DramaForge 开发 Agent 手册

**状态：ACTIVE / Grok 4.5 开发执行入口**

**适用仓库：`D:\调研\dramaforge`**

**执行记录：遵守 `AGENT_EXECUTION_PROTOCOL.md` v3.0。每个 Agent/subagent 在任务开始、完成、失败、暂停或合并时，通过 `.agent-control/control.ps1` 追加本地事实；并行写入由 Git 分支、GitHub PR 和独立 worktree 隔离。没有观察器、Session、Token、心跳或进程门禁。**

**目标执行者：Grok 4.5 或其他编码 Agent**

**当前事实：代码仓已独立初始化，但尚无 `frontend/`、`backend/`、`docker-compose.yml` 等应用代码。**

**目录边界：所有应用代码、迁移、测试、fixture、运行手册和开发状态只能写入 `D:\调研\dramaforge`；`D:\调研\项目` 是外部研究与源资料目录，不是开发工作区。**

## 0. 交给 Grok 4.5 的启动指令

在 Grok 4.5 的代码执行环境中将工作目录设为 `D:\调研\dramaforge`，并发送以下指令：

```text
确认当前工作目录是 D:\调研\dramaforge。读取仓库根目录 agent.md，并把它作为本项目开发执行入口。
所有项目代码、测试、迁移、fixture 和开发文档只能写入 D:\调研\dramaforge；不得在 D:\调研\项目 或其他目录建立代码副本。
先执行 `.agent-control/control.ps1 -Operation open` 和 `tail -Tail 20`，再核验 `git status --short`、`git worktree list`、`git branch --all` 和 GitHub 远端状态。不要依赖聊天记忆，不要覆盖已有未提交改动。
从 agent.md 的“当前唯一下一步”开始执行 Task BOOT-0.1；不要一次性开发 S1-S5。
开始 Task 或 subtask 前写 STARTED；完成、失败或暂停时立即写 COMPLETED、FAILED 或 PAUSED。记录摘要、分支、worktree、改动文件、测试、commit、证据和下一步。
允许主 Agent 使用多个 subagent：只读调查可以并行；有基线提交后，每个写入 subagent 必须使用独立 `agent/<task-id>` 分支和 `.worktrees/<task-id>`，提交并推送同名 GitHub 分支。主 Agent复核 diff 和测试后通过 PR 或明确合并顺序进入 main，并记录 MERGED。每个 subagent 必须自行记录开始和结束状态。
遇到真实 Provider 费用、外部账号、不可逆操作或冻结合同冲突时先停止对应动作并说明；其他本地开发自主完成。
```

不要只让 Grok “阅读后给计划”。上述指令授权它实现当前 Task，但不授权跳过 Gate、扩大 P0、使用真实付费服务或执行 Git 破坏性操作。

## 1. 你的任务

你是 DramaForge 的主开发 Agent。你的目标不是制作界面原型，也不是一次性生成大量占位代码，而是严格依据冻结合同，按 Gate 把项目从空规格仓实现为可供 1–6 人短剧团队内部试产的 P0 MVP。

P0 完成后的真实产品效果是：团队可以在私有部署环境中，从创意或剧本建立同一个正式 Project，维护角色、场景、道具和参考资产，完成至少 10 个 Shot 的图像、视频、语音、字幕、合成、一致性检查、审核、局部返工和交付；每次 Provider 调用、输入、成本、失败、产物和人工决定均可追溯。

最终 P0 交付物固定为：

- 可运行的 React/FastAPI/PostgreSQL/Redis/MinIO/Arq 应用。
- 快速模式与专业工作台共享同一个 Project 和同一套业务事实。
- 一份 3–5 场、至少 10 Shot、至少 1 名主角的冻结黄金样本。
- 可重现的 MP4、SRT、素材包和 `timeline_json` 交付。
- 自动化测试、迁移、OpenAPI 类型、运行手册和验收证据。

P0 不是 LibTV、Jellyfish、Toonflow 或 ArcReel 的复刻。DramaForge 的核心侧重点是团队私有化、Production Graph、角色与剧情连续性、受控返工、预算和审计。

## 2. 指令优先级与事实源

开始任何工作前，按以下顺序读取本地文件。上层文档覆盖下层文档：

1. 用户当前明确指令。
2. [`01_项目总需求.md`](01_项目总需求.md) 至 [`06_受控混合Agent运行时规范.md`](06_受控混合Agent运行时规范.md)：P0 唯一冻结实施合同。
3. [`AGENT_EXECUTION_PROTOCOL.md`](AGENT_EXECUTION_PROTOCOL.md)：本地记录、多 subagent、Git 分支/worktree、GitHub PR 和中断恢复规则。
4. `.agent-control/PROGRESS.jsonl` 尾部与 `open` 结果：本机执行断点；不属于产品运行时，也不进入 Git。
5. `docs/开发执行检查点.md`：实际进度、已完成 Gate、阻塞和唯一下一步。代码仓初始化时已创建，BOOT-0 开始前必须先更新。
6. 当前 Task 明确引用的冻结条款、ADR、测试和运行手册。
7. [`docs/产品阶段与效果路线图.md`](docs/产品阶段与效果路线图.md)：仅在判断产品阶段边界时读取。
8. [`docs/MVP能力延期台账.md`](docs/MVP能力延期台账.md)：仅在判断 P0 外能力时读取。

默认禁止把以下文件加入当前 Task 的上下文：`AI短剧工作台完整实施规划.md`、`DramaForge架构决策与技术选型书.md`、`DramaForge双模式产品与架构汇报方案.md`、P1/P2 ADR，以及 `D:\调研\项目` 下的研究资料。只有当前 Task 明确需要解释决策背景时才可只读打开；它们不能产生实现任务、目录、接口或排期。

发现冲突时，不要自行挑选更容易实现的一方。先引用冲突文件与条款，在 `docs/开发执行检查点.md` 记录，再停止冲突范围的实现；其他不受影响的工作可继续。

### 2.1 阶段编号消歧

当前权威工程顺序是冻结包定义的：

```text
BOOT-0 仓库启动
  → S0-A 视觉一致性 Spike
  → S0-B 剪映兼容性 Spike（可因外部环境延后，不阻断主交付）
  → S1 可信基础骨架
  → S2 快速模式首帧垂直切片
  → S3 Production Runtime 加厚
  → S4 10 Shot 专业生产与审核闭环
  → S5 交付和集成硬化
  → P0 MVP 完成
```

旧文档 `S0-S4_按冻结包落地清单.md` 把仓库骨架称为 S0，并采用另一套 S1–S4 切分。不要按该编号汇报当前进度，也不要把其中的 S4 当成 P0 完成。可吸收其竖切、迁移和测试建议，但阶段名、范围和 Gate 以 `01`–`06`、产品路线图和本文件为准。本文将仓库初始化单列为 `BOOT-0`。

## 3. 永远不能破坏的边界

1. 技术栈固定：Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2 async、asyncpg、Alembic、PostgreSQL 15+、Arq、Redis 7+、MinIO、React 18、TypeScript、Vite、TanStack Router/Query、Zustand、SSE、FFmpeg、InsightFace。
2. 目录严格遵守 `03`。不得新建 `common`、`helpers`、`misc`、`utils2`、`services2` 或平行应用。
3. 调用方向固定为 Route → Service → Repository/Domain；Route 不写 SQL，业务 Service 不直接调用 Provider、Redis、Arq 或 FFmpeg。
4. 业务状态、`event_log` 和 Outbox 在同一 PostgreSQL 事务提交。Redis 不是业务真相源。
5. API 与 Worker 都必须建立 PostgreSQL RLS 上下文。Worker 只信 run ID 与 dispatch generation，身份和项目必须回源数据库。
6. Artifact 二进制只存 MinIO；数据库只保存 object key、哈希和媒体元数据。Artifact 固定字段不可变。
7. GraphVersion 发布后不可变。Graph、GraphVersion、GraphNode/Edge、NodeRun、ProviderOperation、Artifact 不得合并成一张“任务表”。
8. 数据合同变更必须同步修改 Alembic DDL、SQLAlchemy ORM、Pydantic、OpenAPI 生成类型、Command、fixture 和测试。
9. 快速模式和专业模式只能使用同一个 Project、资产、Graph、Run、成本和审核事实，禁止第二套聊天项目或草稿数据库。
10. Agent 只做严格 Schema 的 Brief/Plan 推理。模型没有写入型 Tool，不得直接写数据库、文件或执行生产任务；物化只能经用户确认后的 `materialization-p0-v1` Command 白名单。
11. 所有真实 Provider 调用均使用用户 BYOK，先授权、预算预占，再创建 ProviderOperation 并记账。不得使用隐藏平台 Key 或跨账号代付。
12. 不得把密钥、完整提示词/响应、Embedding、永久对象 URL 写入日志、SSE、Outbox、普通 API 或交付包。
13. `shot-p0-v1` 的节点、命名端口和边是 P0 固定合同。阶段切片可以暂不启用后续节点，但已进入 S4 的实现不得删除、合并或运行时跳过节点；手工媒体只能作为已注册节点的受审计结果进入 Graph，并继续经过正确下游。
14. P0 一致性检查不能通过配置关闭。可以配置阈值、规则等级、自动修复次数和转人工条件；所有实际生成图像与所有可交付 Shot 仍须执行冻结合同规定的角色和剧情检查。

## 4. P0 明确不开发

以下内容不能以“先预留”“隐藏路由”“空表”“feature flag”或“做个界面以后再接”为理由进入 P0：

- 多候选结果池、废卡复用、Candidate 到 Asset/Reference 提升：P1.1。
- 评论、任务指派、完整团队协作和实时共同编辑：P1.2。
- 无限画布、富故事板、受控精剪、FCPXML、OpenCut：P1.3；OpenCut 还必须先通过独立 Spike。
- 3D 导演台、走位与高级机位预演、EDL/AAF：P2。
- 通用 NLE、插件市场、自由 Agent/MCP Runtime、用户自定义工作流、公有 SaaS 支付、Kubernetes、WebSocket、跨项目公共缓存：禁止。
- Adobe Premiere `*.prproj` 兼容或逆向：禁止。

遇到上述需求时，记录到延期台账或引用现有条目，不写代码。

## 5. 每次会话的固定工作流

每次开始执行时必须按以下顺序工作：

1. 核验当前工作目录和 Git 根目录均为 `D:\调研\dramaforge`；不是则停止写入并切换目录。
2. 执行 `open` 和 `tail -Tail 20`，然后检查 `git status --short`、`git worktree list`、`git branch --all` 和 `git remote -v`。
3. 对未闭合任务检查其分支、worktree、commit、diff 和测试；根据事实补记 COMPLETED、FAILED 或 PAUSED，不盲目重跑。
4. 读取 `agent.md`、执行协议、开发检查点和当前 Task 明确引用的冻结条款。
5. 从“唯一下一步”选择一个最小闭环并写 STARTED；若交给 subagent，先登记唯一 task_id、分支、worktree 和文件范围。
6. 先写失败测试或验收夹具，再做最小实现；保留真实测试命令和结果，不用口头结论替代证据。
7. 同步更新迁移、OpenAPI 类型、文档、运行手册和验收证据，不能留下只改一层的合同漂移。
8. Task 完成、失败或暂停时更新开发检查点并立即写对应状态；合并进入 main 后由主 Agent写 MERGED。

### 5.1 多 subagent 默认策略

- 主 Agent 为每个委派分配唯一 task_id；派出前记录任务、目标分支、worktree、文件范围和验收命令。
- 只读 subagent 可以并行，不需要 worktree；它仍须自行记录 STARTED 和结束状态。
- BOOT-0 初始基线提交之前写入保持串行。基线提交后，每个写入 subagent 使用独立 `agent/<task-id>` 分支和 `.worktrees/<task-id>`，不得共用主工作区。
- 写入 subagent 在自己的分支提交并推送 GitHub，不直接改 main；主 Agent检查 diff、测试和合同后创建/复核 PR，再按依赖顺序合并。
- 尽量按文件所有权拆分。多个分支修改同一文件时，分支不会自动消除冲突，主 Agent必须负责解决冲突和合并后联合测试。
- subagent 的汇报不是完成证据。至少记录 changed_files、tests 和 commit；主 Agent合并后记录 MERGED。
- 中断后通过 `open`、Git 分支、worktree、commit 和未提交 diff 找到断点，不依赖进程状态或聊天记忆。
9. 输出简短开发报告，不宣称未通过 Gate 的阶段已经完成。

只有以下情况询问用户：

- 需要真实 BYOK、付费 Provider 调用、购买额度或登录外部账号。
- 需要下载安装依赖但网络或权限受限。
- 需要在外部应用中验证剪映等格式，或执行具有副作用的外部操作。
- 冻结合同真实冲突，且会改变需求、技术、目录、数据或运行时行为。
- 需要删除用户数据、重写 Git 历史、覆盖既有改动或执行不可逆操作。

本地编码、mock 测试、修复普通错误和更新检查点不需要反复询问。

## 6. 工程方法与完成定义

### 6.1 切片原则

- 每个 Task 必须有一个用户可观察结果，或一个可独立证明的运行时不变量。
- 不接受“目录和类都建了”作为业务完成；薄骨架只在 BOOT-0 合理。
- 不为未来阶段设计抽象。只实现当前 Gate 需要且冻结合同已经定义的接口。
- 当前 Task 的窄切片只限制本阶段实施面，不缩小 P0 最终完成范围；S2 首帧切片、S4 全节点生产和 S5 正式交付不得互相替代。
- 数据迁移按行为分期。当前阶段未使用的表不为追求“齐全”而提前铺开；某张表一旦进入阶段，必须逐字段镜像 `04`，不得用临时简化列、自由 JSON 或 SQLite 行为代替。
- 外部 Provider 在接入前先通过 fake Adapter 的状态机、预算、重放和错误契约测试。
- 前端服务端状态只放 TanStack Query；Zustand 只保存布局、选择和临时 UI 状态。
- UI 首先服务高频生产：项目、Brief/Plan、资产、Shot、任务状态、审核、成本和交付。P0 不做营销首页。

### 6.2 一个 Task 只有同时满足以下条件才算完成

- 行为与当前阶段验收项一致。
- 正常、失败、权限和幂等路径有自动化测试。
- 使用真实 PostgreSQL 验证数据库/RLS 行为，不用 SQLite 替代。
- Ruff、mypy、pytest、ESLint、Prettier、`tsc --noEmit`、Vitest 中所有受影响检查通过。
- 跨前后端行为具备 Playwright 或等价验收证据。
- Pydantic 改动后已重新生成并提交 `frontend/src/types/api.ts`。
- 没有提交密钥、用户真实数据、缓存、构建产物和测试临时文件。
- 检查点已更新，并列明真实执行命令和结果；未运行的测试必须明确写出原因。
- 本 Task 最新日志状态不是 `STARTED` 或 `PAUSED`；写入任务已有可复核 commit，合并任务已有 PR/merge 证据。

### 6.3 提交纪律

- 一个提交只对应一个可验证 Task；不要把整个阶段塞入一个提交。
- 提交前查看 `git diff`，只暂存本 Task 文件，不包含既有用户改动。
- GitHub 私有远端核验后，写入 subagent 必须推送自己的 `agent/<task-id>` 分支；不得直接推送业务改动到 `main`。初始基线由主 Agent单独提交并推送。
- 合并由主 Agent在审查 diff 和测试后通过 PR 或明确顺序执行；禁止 force push、历史重写或未审查自动合并。
- 不使用 `git reset --hard`、`git clean -fd`、`git checkout -- <file>` 清理工作区。

## 7. 开发阶段和 Gate

### BOOT-0：把规格仓变成可开发仓

**目标效果**：新开发者能按 README 启动基础设施、API、Worker 和前端壳；所有质量命令有统一入口，之后的代码有明确落点。

任务：

1. 读取并更新 `docs/开发执行检查点.md`，记录 BOOT-0 计划操作、仓库状态和唯一下一步。
2. 创建 ADR `docs/adr/0001-migration-slice-strategy.md`。迁移采用分期策略，但每个已实现字段必须逐字段镜像 `04`，禁止临时简化表；ADR 不修改冻结合同。
3. 严格按 `03` 建立根目录、后端、前端、基础设施、脚本、fixture 和 docs 子目录。未进入当前阶段的业务文件可建立最小 import-safe 壳，但不要伪造完成状态。
4. 建立 Docker Compose：PostgreSQL、Redis、MinIO、API、default Worker、heavy Worker；GPU 和 ComfyUI 只放条件 profile，不默认启用。
5. 建立 FastAPI `/health`、配置校验、统一错误壳和 v1 router；建立 React 应用壳、QueryClient、TanStack Router 和基础工作台布局。
6. 建立 Ruff/mypy/pytest、ESLint/Prettier/TypeScript/Vitest/Playwright、OpenAPI 类型生成和目录合规检查。
7. 创建 `.env.example`，仅使用假值并说明密钥生成方式；补充本地启动与测试 README。

BOOT-0 Gate：

- `docker compose config` 通过，PostgreSQL/Redis/MinIO 健康。
- API `/health` 返回 200，Worker 可启动，前端可打开且控制台无错误。
- 后端静态检查和最小测试通过；前端 lint、类型、单测和 build 通过。
- OpenAPI 类型可重复生成且 diff 干净。
- 目录检查能拒绝未登记目录和敏感/构建文件。
- 检查点包含命令、结果和失败项。

### S0-A：视觉一致性 Spike

**目标效果**：用数据判断 InsightFace 是否足以作为 P0 的角色一致性执行门，并得到可复现阈值依据。

任务与 Gate：

- 只使用 `scripts/run_s0_face_spike.py`、`fixtures/images/character_canonical/` 和 `docs/spikes/` 规定的路径。
- 至少包含 20 对同角色、20 对异角色和 10 个无脸、多脸、遮挡或低质量异常样本。
- 使用 InsightFace 0.7+、ONNX Runtime CPU，输出 512 维归一化向量。
- 报告 FAR、FRR、阈值候选、异常分类、人工标注一致性、平均/分位耗时和环境版本。
- 原图和 Embedding 不进入日志、Git 中的公开报告或普通 API fixture；报告使用脱敏样本 ID。
- 样本不足时不得编造结论。将阶段标记 `BLOCKED_BY_FIXTURE`，列出所需样本和采集规范；BOOT-0/S1 可继续，真实一致性 Gate 不得宣布通过。

### S0-B：剪映兼容性 Spike

**目标效果**：决定剪映草稿是否可作为 P0.5 可选出口，而不是让私有格式绑住 P0。

任务与 Gate：

- 只使用 `scripts/run_s0_jianying_spike.py` 和 `docs/spikes/` 记录目标剪映版本、最小媒体、轨道、字幕、重开结果及失败策略。
- 需要真实外部应用或 GUI 时先请求用户授权，并在检查点记录计划和结果。
- 验证失败或当前环境不可用时，将剪映保留为 P0.5，不阻断 MP4、SRT、素材包和 timeline JSON 主交付。
- 未通过前，不注册 `jianying_draft` 路由、开关、依赖或 P0 验收项。

### S1：可信基础骨架和双模式应用壳

**目标效果**：两名不同权限成员能进入同一项目；快速入口和专业入口打开同一个 Project；越权、断线和重复事件不能破坏数据。

必须实现：

- Cookie 会话、CSRF、Organization/Project/Membership、BYOK 加密边界。
- `04` 定义的相关全量字段、枚举、FK、触发器、索引和逐表 RLS；应用角色不可是 owner、superuser 或 `BYPASSRLS`。
- EventLog、Transactional Outbox、死信、Redis Streams、SSE 续传和快照重取骨架。
- Outbox pending 数与最老等待时长、lease 超时/补偿、死信数和 SSE 重连次数的基础 Prometheus 指标；建立可执行的死信查看与人工重放 runbook 草稿。
- Production Graph 数据模型、不可变发布边界、NodeRun/ProviderOperation/Artifact 分层。
- Creation Experience 稳定 Interface、正式 Project、手工初始 Brief、模式偏好和同项目路由；`start_project` 不调用文本 Provider。
- 快速/专业模式共用 ProjectSnapshot，前端不能维护第二套服务端实体。

S1 Gate：

- 两用户跨项目读取、写入、Worker 和对象 URL 越权均被拒绝。
- RLS 连接池上下文无泄漏。
- Outbox 重放、重复投递、死信和 SSE `Last-Event-ID` 恢复测试通过。
- 基础指标可被 Prometheus 抓取；可按 runbook 定位并重放一条测试死信，且不会产生重复业务副作用。
- Graph 发布不可变，命名端口/DAG 校验通过。
- 同一项目可从两个入口打开，ID、资产、成本和状态一致。
- 未经规划授权时文本 ProviderOperation 数量为零；无 Key 手工路径可用。

### S2：快速模式首帧垂直切片

**目标效果**：用户从创意或文本开始，经费用授权、Brief/Plan 两级确认，生成一张受角色一致性检查的首帧，并在专业工作台看到同一个 Run、Artifact 和成本。

固定路径：

```text
start_project
→ 手工或受控 Agent Brief
→ confirm_brief
→ 手工或受控 Agent Plan
→ confirm_plan + materialization-p0-v1
→ 发布合规 GraphVersion
→ Keyframe NodeRun
→ Flux Adapter
→ Artifact 入 MinIO
→ InsightFace Review
→ Outbox/Streams/SSE
→ 同项目专业工作台
```

约束：

- S2 真实图像 Provider 只能是 `flux`；文本只使用已配置且已授权的 `openai` Adapter。
- 先以 fake Adapter 跑通全部契约；真实调用前必须得到用户 BYOK 与费用授权。
- 每个文本 primary/repair/retry/fallback 分别产生 ProviderOperation 和实际账本分录；AgentRun 不保存第二套 Provider/成本事实。
- 无文本 Key 时可以手工完成 Brief/Plan；缺少 canonical Reference 时拒绝首帧生成。
- 格式错误最多一次有预算的 schema repair；stale 或取消后的晚到 Agent 输出不能写回。

S2 Gate：

- API → Graph → Outbox → Arq → Adapter → Artifact → Review → SSE 全链可重放。
- 关浏览器后任务继续，重开后从 PostgreSQL 快照恢复。
- Artifact 哈希、输入版本、ProviderOperation、费用和审核可回链。
- 快速模式切换到专业模式无需复制或人工搬运数据。
- 真实 Provider 证据与费用写入受控验收记录，不写入密钥。

### S3：Production Runtime 加厚

**目标效果**：系统面对并发、重试、预算、取消、回调乱序和服务重启时仍不重复扣费、不静默覆盖、不错误触发下游。

必须实现并测试：

- `shot-p0-v1` DAG 的输入 hash、拓扑执行、命名端口、单飞、缓存和正确下游 stale 传播。
- 缓存命中新建 `NodeRun(status=cached)`，复用同一不可变 Artifact，ProviderOperation 和真实成本为零。
- 预算预占、成功/失败/取消结算、释放、晚到费用和超额冻结。
- 幂等取消、远端取消、`completed_after_cancel` 和人工采纳边界。
- Provider Inbox 签名、重放去重、乱序事件与轮询共用 CAS 状态迁移。
- queued 补偿扫描、lease/dispatch generation 恢复、Outbox 重试/死信/归档。
- Artifact quarantine/available/cold/delete_requested/deleted 生命周期、回温和引用保护。
- 统一错误码、可操作失败建议、Prometheus 指标和 runbook。

S3 Gate：冻结包要求的缓存命中、预算不足、取消竞态、Outbox 重放、死信、Provider 回调重放、冷存储回温失败、SSE 恢复和 RLS 越权演练全部通过。

### S4：10 Shot 专业生产与审核闭环

**目标效果**：内部团队可用 3–5 场冻结剧本完成至少 10 个 Shot 的生产、审核和局部返工，人工锁定内容不会被 Agent 覆盖。

必须实现：

- `.txt`/`.md` 剧本导入与 Episode/Scene/Shot 人工编辑。
- Character、Scene、Prop、Style、canonical Reference 和 Reference Set。
- `shot-p0-v1` 全节点：prompt、keyframe、face review、video、video drift review、voice、subtitle、composite、continuity review。
- Flux、Kling、Azure TTS 固定 Adapter；未配置 Key 时显式失败或走可批准的手工媒体节点结果，不隐式代付。手工路径不得删边或跳过节点，必须记录操作者、来源、文件哈希、媒体元数据、审核状态和零 Provider 成本；实现前先用 ADR 固定 Command、权限、幂等和 Artifact 写入合同。
- 角色七层防线、剧情连续性四层、自动修复次数上限、人工 Review 和 Violation。阈值、规则等级和转人工策略可配置，但检查本身不可关闭；明确违反 `block` 规则的结果不能以人工降级名义自动放行。
- 专业工作台的 Shot、依赖、状态、成本、失败、审核、人工锁和局部重跑操作。
- 黄金样本 fixture、Provider mock、预期 hash、审核和成本事实。

S4 Gate：

- 至少 10 Shot 可分别成功、失败、审核、修复和重跑。
- 所有生成图像完成人脸检查；所有可交付 Shot 完成剧情连续性检查。
- 修改字幕只让 Subtitle、Composite 和正确下游失效，Keyframe、Video、Voice 保持缓存或未受影响。
- 人工锁定资产、分镜和已审核结果不被快速模式或晚到 Agent 输出覆盖。
- 不需要开发者改数据库或手工修队列才能走完生产审核。

### S5：交付和集成硬化

**目标效果**：同一黄金项目可以从任一模式发起正式交付，交付包可校验、可下载、可重新生成，并回链全部来源和成本。

必须实现：

- 版本化 timeline JSON、SRT、受控 FFmpeg 合成、MP4 和素材包。
- Export/ExportItem 固定来源清单、审核 Gate、哈希、授权下载和 Artifact 生命周期保护。
- 10 Shot Playwright E2E、Worker/Redis/Provider 故障恢复、性能与安全回归。
- 私有化部署文档、备份恢复、密钥轮换、死信处理、对象生命周期和验收 runbook。
- 验收记录包含版本、fixture 哈希、Provider 配置摘要、费用、失败项和人工批准人。

S5 / P0 Gate：

- `01` §3.1 的 18 条端到端条件全部通过。
- MP4、SRT、素材包和 timeline JSON 可从固定输入重现并校验哈希。
- 团队无需工程师手工修库、补队列或拼对象存储文件。
- 所有 P0 非功能演练通过，未通过项不得用“已知问题”替代 Gate。
- 只有此时才可将产品状态写为“P0 MVP 完成”。S2、S3 或 S4 均不能提前宣布 MVP 完成。

## 8. P0 完成后的顺序

P0 完成并用真实团队项目验证后，按以下顺序另行立项和更新合同：

1. P1.1：候选结果治理与项目内复用。
2. P1.2：评论、指派、审片和责任闭环。
3. P1.3：富故事板/画布、受控精剪、FCPXML；OpenCut 只作为通过 Spike 后的可选 Adapter。
4. P2：3D 导演台、高级预演和更专业的后期互操作。

开始 P1/P2 前必须形成正式 PRD、ADR、迁移、API、Command、fixture 和测试，并同步修改受影响的 `01`–`06`。不得直接拿调研文档实现。

## 9. 当前唯一下一步

收到“开始开发”或等价指令后，执行以下 Task，不要同时铺开 S0–S5：

```text
Task BOOT-0.1
1. 核验工作目录与 Git 根目录都是 D:\调研\dramaforge。
2. 执行 open 和 tail；检查 Git 状态、worktree、分支、远端和未闭合任务。
3. 为 BOOT-0.1 写 STARTED，读取检查点和当前 Task 相关冻结条款。
4. 创建 docs/adr/0001-migration-slice-strategy.md，并建立可提交的初始基线；BOOT-0 初始提交之前写入保持串行。
5. 核验 GitHub 私有远端后推送 main 基线。不得使用已暴露或写入文件的访问令牌。
6. 按 03 拆分后续竖切；每个写入 subagent 使用独立 agent/<task-id> 分支和 .worktrees/<task-id>，自行记录 STARTED 和结束状态并推送 GitHub 分支。
7. 主 Agent通过 diff、测试和 PR 审查各分支，按依赖顺序合并并记录 MERGED。
8. 用 mock/本地基础设施完成 BOOT-0 Gate，更新检查点并记录 BOOT-0.1 的 COMPLETED、FAILED 或 PAUSED。
```

BOOT-0 未通过前，不接真实 Provider、不实现候选池、OpenCut、无限画布或导演台，也不宣称业务 MVP 已开始可用。

## 10. 每轮报告格式

每轮执行结束只报告可验证事实：

```text
阶段 / Task：
完成：
用户可观察效果：
改动文件：
验证命令与结果：
未验证或阻塞：
外部调用与实际成本：
检查点：docs/开发执行检查点.md
本地进度：.agent-control/PROGRESS.jsonl
分支 / PR / commit：
下一步唯一操作：
```

不要用“应该可以”“基本完成”“理论上通过”代替测试证据。未运行的命令、缺失的环境、缺少的 Key 和尚未验证的真实 Provider 必须明确写出。
