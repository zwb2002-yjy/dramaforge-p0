# V1_STATUS — 当前 V1 / 发布状态

Status: current  
Date: 2026-09-18（本节为最新实测；下方"当前结论"及历史小节保留其原始日期与语境）  
Branch: `dev` = `9456f6c999ed661e3585b6f578563dbebf9dea40`（= `origin/dev`）；`main` 基线仍为 `c12c3dfb`

> 2026-09-18 重要更正：本文件此前记录的"当前候选"是 `b96a5216` / PR #90 HEAD `d2c7655b`
> 时期的状态。当前 `dev` 已推进到 `9456f6c`，且**工作区有大量未提交改动**（139 个路径，
> 含另一 agent 正在进行的前端/导航/设置重构）；本文件的验证数字与"正式 8080 实例身份"
> 两处已与实际不符，见文末「2026-09-18 工作区实测」。发布完成条件本身未变。

## 当前结论

第一版创作主链和发布打包修复已经进入 `dev`，但**当前不能标记为正式发布完成**。

当前发布 PR 为 **#90：`dev -> main`**，HEAD 为 `d2c7655b`，GitHub 返回
`mergeable=true`；`main` 基线仍为 `c12c3dfb`。Owner 仍是唯一合并人。
（该 PR 事实来自 2026-09-17 记录，本轮未复核远端 PR 状态。）



### 8080 当前候选运行事实

- 从 `0a38ce9` 构建的本地正式拓扑已在 8080 启动；gateway / API / 数据库健康检查通过，运行环境为 `production`，运行身份与提交一致。
- 在该全新实例中通过界面初始化 Owner，并通过规范剧本导入链导入“乌镇宣传短片”：1 集、1 场景、6 镜头，剧本文档版本 1，内容哈希保持一致。
- 方案授权范围内已完成 Agnes 账户模型绑定和非付费 `auth_models` 验证。一次真实关键帧提交已按唯一幂等键发送并最终失败；真实错误为当前项目 16:9 与 Agnes 冻结模型清单要求 9:16 不一致。未盲目重试或伪造成功。
- 因此 8080 健康与脚本闭环已验证，但 REL-01 的真实媒体、恢复、安装和最终发布条件仍未满足。
### 本轮已验证的当前候选事实

- 当前 `dev` 已实现精确候选审查目标：普通候选与修复步骤都绑定不可变 Artifact，错误目标失败关闭，不回退 Formal。
- Review 摘要已返回视频证据清单：来源 Artifact / 哈希、审查 NodeRun / Artifact、采样版本、参考图哈希和逐帧可用状态；桌面证据条只读并定位播放器。
- 当前候选质量镜像已通过 1228 单元测试、84 PostgreSQL 集成测试；前端通过 268 单元测试、45 Playwright 测试。
  （**历史数字**，属上述旧候选；当前工作区的实测数字见文末「2026-09-18 工作区实测」。）
- 已从当前提交启动正式 8080 拓扑并验证 gateway/API/数据库身份；在该实例初始化 Owner、创建“乌镇宣传短片”并导入 1 集 / 1 场景 / 6 镜头剧本。
- 上述运行验证没有发起付费 Provider 生成；因此不能替代真实模型 Golden、异常恢复全矩阵和发布物安装验证。
## 还差什么

### 1. GitHub required checks 需要真正跑起来

`d2c7655b` 上最新 CI 与 Security workflow 都以 failure 结束，而且所有实际 job
都没有执行 step。当前问题发生在 hosted runner 分配/账号层，而不是某个测试命令失败。

本地 Docker 质量门仍可用于开发验证，但不能把“本地通过”写成“GitHub required checks
已通过”。如果改用其他 runner，需在单独变更中明确 runner 环境和发布适配边界。

### 2. REL-01 需要在正式 8080 入口闭合

此前真实 Provider 验收在隔离候选栈完成了主要阶段，但验收 driver 没有形成最终
`complete=true`：16 条必需断言中记录了 10 条，另外 6 条外部/跨阶段断言未导入。

当前 `dev` 已修正两个会阻止闭合的问题：

- migration head 从候选仓库自身推导，不再写死旧 revision；
- 验收入口端口可配置，默认正式入口为 **8080**。

发布验收应以 8080 为正式入口；8088 只适合作为隔离候选/测试端口，5173 只用于前端
开发。最终需要在同一候选 SHA 上完成浏览器、runtime、recovery 等外部证明并执行
`collect`，直到 required assertions 全部满足。

### 3. 发布物还需要最终安装验证

Release workflow 已包含以下修复：打包前回收 runner 磁盘、离线包扁平化、
`images.tar.gz` 单趟压缩，以及 `worker-director` 的生产必需环境变量。

这些改动仍需在可运行的 release workflow 上重新生成正式制品，并用生成出来的
online/offline bundle 做一次干净目录安装验证。只有源码测试通过不能替代发布物验证。

## 发布完成条件

V1 发布完成至少同时满足：

1. 当前候选的 CI / Security required checks 真实执行并通过；
2. 同一候选在正式 8080 入口完成 REL-01，最终 `complete=true`；
3. Owner 审阅并合并 `dev -> main`；
4. Release workflow 成功生成并发布版本化制品；
5. 对实际生成的安装包完成在线/离线安装、启动与健康检查验证。

## 证据和历史记录放哪里

当前树只保留可重复执行的验证逻辑，例如 CI、单测、E2E、release contract 和
`scripts/prove_v1_r7_acceptance.py`。真实 Provider 调用明细、阶段报告、旧候选审计和
一次性修复过程不再写入长期文档；需要追溯时查看 Git 历史，临时运行证据写入 `tmp/`。

### 乌镇 9:16 真实关键帧进展

- 在“乌镇宣传短片（首版竖屏）”中，六个镜头均已完成设计保存、执行计划冻结和 Agnes 真实关键帧生成；每次提交使用独立幂等键并完成回执对账。
- 六个候选 Artifact 已进入候选托盘，正式版本指针仍为空。系统停在逐候选人工审查与 Formal 的显式用户门，没有替用户自动通过。
- 16:9 原项目的能力不匹配失败保持为真实失败证据，没有被静默改画幅或重复提交。
### 安装包本地烟测

当前候选已在临时隔离目录完成离线安装烟测：本地构建的运行镜像集单趟压缩、gzip 完整性、`docker load`、`install.ps1 -Offline` 和全 Compose 健康检查均通过。该证据仅证明本地安装路径，不能替代 Release workflow 产物、CI required checks 或最终发布身份。

## 2026-09-18 工作区实测（第 26 轮更正，第 29 轮更新）

口径：本节描述的是**当日工作区**的实测事实；第 29 轮已把该工作区整体冻结为提交
**`a5d5851`**（见下「候选已冻结」），因此本节的门禁结果现可作为该候选的提交级证据读取。

**身份**

- 候选提交：**`a5d585199…`**（`dev`，已推送 `origin/dev`，工作树干净）。
  该候选含三个提交：`581071c` 本次修复、`14e40df` 并行进行的导航/创建选项/设计系统工作、
  `a5d5851` 用户方案文档。
- `main` 仍为 `c12c3dfb`；`origin/main` 未前进。
- 提交时（同一棵工作树）实测门禁全绿：后端 ruff/mypy + **1246** 单测；前端 format/lint/typecheck
  + **323** 单测 + build + routes:check + **76** e2e。
- **CI 触发条件注意**：`.github/workflows/ci.yml` 只监听 `pull_request`（到 `dev`/`main`）
  与 `workflow_dispatch`，**push 到 `dev` 不会自动触发 CI**。要让 required checks 真实执行，
  需要打开/更新指向 `dev` 或 `main` 的 PR，或手动 dispatch。

**本工作区实测通过的门禁**

| 门禁 | 结果 |
|---|---|
| 后端单测 | 1246 passed |
| 后端集成（真实 Postgres + Redis） | 84/84 passed |
| `ruff` / `mypy` | 全通过 / 286 源文件无问题 |
| `alembic check` | No new upgrade operations detected（模型与迁移一致） |
| 前端单测 | 323 passed / 64 文件 |
| 前端 e2e（Playwright，含 v1 主链旅程） | 76 passed |
| 前端 `format:check` / `lint` / `typecheck` / `build` / `routes:check` | 全通过 |
| `api:check`（生成类型 vs OpenAPI） | generated.ts is up to date |
| 后端集成环境注意 | 在 `dramaforge-v1-release-quality_default` 网络上必须用容器名 `dramaforge-redis-quality-1`；别名 `redis-quality` 只存在于 `dramaforge_default`，用错会得到 4 个假失败 |

**当前 8080 运行实例的真实身份（与上文历史记录不同）**

- `GET /health` 报告 `env=development`、`source_commit=9456f6c`；
  API 容器 `APP_ENV=development`、`SESSION_SECRET=dev-only-change-me-…`。
  这是**本会话用于实时验证的开发环境实例**，不是发布身份实例。
- 前端镜像是 **2026-09-02 构建的 `c44df24` 版本**（`org.opencontainers.image.revision`），
  落后于 `9456f6c`：本会话修复的前端行为（镜头画布四项可写、失败原因中文呈现、
  词表兜底与泄漏清理）**在 8080 上尚不可见**，只在 5173 开发服务器可见。

**已知限制（首版范围）**

- 镜头 6 没有正式视频：其视频提交处于 `unknown_submission`（远端任务编号缺失，
  禁止盲目重试）。Owner 已确认未找到可对账的远端任务；该镜头按已知限制处理，
  待 Owner 决定"重提"或"记录为首版限制"。

**剩余待决策项（阻塞继续推进的不是代码，而是决策）**

1. 资格门禁语义：`quality_gated` 是硬准入门禁还是质量认证信息（两条最小方案与影响见
   `tmp/p0-evidence/eligibility-gate-audit/ELIGIBILITY_GATE_AUDIT.md`）；
2. 死表面处置：#13 制作工作台非实验部分（应用内不可达）、#15 `ExperimentCompare`
   无消费者、#6 导演提案路径无生产者——删除或接线属产品决策；
3. 跨 agent 协调项：#9 项目级绑定读取接口、#10 供应商连接启停/删除（消费端都在
   另一 agent 正在修改的文件里）。

**阶段 12 一致性审计**（方案 1498-1594 行要求）已完成：用户动作清单（53 条，机械提取）、
四域链路追踪、技术信息泄漏审计 7 问、16 条明确问题与逐条可达性分类，见
`tmp/p0-evidence/stage12-consistency-audit/STAGE12_CONSISTENCY_AUDIT.md`。
其中本会话已修复并现场验证：镜头画布四项不可写、失败原因不可见、参考静默失效、
回收素材可被绑定、实验创建幂等键非确定、以及三类界面词表/错误消息泄漏。