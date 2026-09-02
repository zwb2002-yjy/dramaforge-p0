# DramaForge Agent 执行协议

**状态：强制执行**

**版本：v4.0**

**适用 Goal：DramaForge V1 统一创作主链及其后续 Owner-authorized Goal**

本协议只规定 Agent 如何记录、恢复、提交、验证和连续推进。产品目标、架构事实、任务优先级、付费 Provider 授权和 Goal 完成标准由根目录 `agent.md`、Professional 七方案 README 的最新 Owner amendments 与当前 Task Contract 决定。

---

## 1. 核心原则

1. Task Contract 先于写代码；
2. 当前代码、迁移、测试、CI 和运行证据说明真实状态；
3. 每次只执行一个 bounded Task；
4. 普通失败由 Agent 自行诊断、修复和回归；
5. 完成一个 Task、commit、工作包或 push 不是等待“继续”的理由；
6. 每个 Task 完成后立即重算 Goal Gate，并自动进入下一 `READY` Task；
7. `main` 只接收经过完整验证的 `dev → main` 发布 PR；
8. Agent 不批准、合并自己的 PR，也不伪造 `MERGED`、Golden、用户验收或发布成功；
9. 不以口头汇报代替 Git、测试、合同与证据；
10. 不使用日期排期作为执行控制器，按依赖、Gate 和真实状态推进。

---

## 2. 权威分工

### `agent.md`

定义：

- 当前 Owner Goal；
- 产品与架构事实；
- 工作包顺序；
- 任务选择规则；
- 允许暂停的条件；
- Provider 调用授权；
- Goal 完成标准。

### 本协议

定义：

- Task Contract 必备字段；
- 本地账本；
- 中断恢复；
- Git、branch 与 worktree；
- Task 验证和证据；
- Goal 级发布交接。

### 当前 Task Contract

定义：

- 本次唯一 Outcome；
- owned paths；
- explicit out-of-scope；
- success criteria；
- focused tests 与 required regression；
- 可以记录 `COMPLETED` 的准确条件。

Task Contract 不能改写 `agent.md` 的 Owner Goal，也不能借局部任务恢复已废弃的产品语义。

---

## 3. Task Contract 先于执行

任何 Task 记录 `STARTED` 前，必须在：

```text
docs/plans/professional-program-v2/task-contracts/
```

创建或确认合同，至少包含：

- 唯一、稳定的 Task ID；
- 所属 Goal 与工作包；
- Current Evidence / Drift；
- 用户或测试可观察的 Outcome；
- 前置条件和依赖；
- owned paths；
- 明确非范围；
- 数据、迁移、API、UI、Runtime 影响；
- 安全与 Canonical boundary；
- focused tests；
- required regression；
- Provider 调用计划与证据要求（若有）；
- 完成条件与证据路径。

如果当前没有可执行 Task，主 Agent 应根据 `agent.md` 的 Goal 工作顺序与当前 Gate 创建一个最小、可验证、依赖已满足的 `READY` Task，而不是等待用户拆任务。

不得一次把多个有依赖关系的工作包捆成一个 Task。不得用 Task Contract 创建第二份 Master Plan。

---

## 4. 本地进度账本

本地账本固定为：

```text
.agent-control/PROGRESS.jsonl
```

该文件：

- 只追加；
- 不进入 Git；
- 不包含 secret；
- 从 Git common directory 定位，因此关联 worktree 共用同一账本。

控制脚本提供：

- `log`：追加事实记录；
- `tail`：读取最近记录；
- `open`：列出最后状态仍为 `STARTED` 或 `PAUSED` 的任务。

允许状态：

```text
STARTED   合同已存在，执行已开始
COMPLETED 合同全部完成条件和验收证据满足
FAILED    当前方案被证据否定，已记录替代任务、回滚或终止原因
PAUSED    当前 Task 尚未完成，外部继续条件准确且可验证
MERGED    Owner 已批准并确认 PR 合并；Agent 不得写入
```

Task、工作包、Goal 和合并状态必须分开：

- Task `COMPLETED` 不等于工作包 Gate 通过；
- 工作包通过不等于 Goal 完成；
- PR `MERGED` 不等于 Release Gate 通过；
- 旧 Golden 不等于当前 HEAD Golden。

发现历史记录错误时，不修改旧 JSONL；对相同 `task_id` 追加新的真实状态，并在 `summary`、`evidence` 和 `next_step` 中说明更正。

账本不得包含：

- Access token、BYOK、密码、私钥；
- 完整 Provider 响应；
- 未脱敏请求体；
- 原始受限 fixture；
- 对象存储 signed URL；
- 任何可复用凭据。

---

## 5. 标准记录

### 开始 Task

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 `
  -Operation log `
  -Status STARTED `
  -TaskId <task-id> `
  -Agent <agent-name> `
  -Summary "<可观察 Outcome>" `
  -Branch dev `
  -Worktree . `
  -OwnedPaths "<path-a>;<path-b>" `
  -NextStep "<第一项证据动作>"
```

### 完成 Task

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 `
  -Operation log `
  -Status COMPLETED `
  -TaskId <task-id> `
  -Agent <agent-name> `
  -Summary "<已满足的 Outcome>" `
  -Branch dev `
  -Worktree . `
  -OwnedPaths "<path-a>;<path-b>" `
  -ChangedFiles "<files>" `
  -Tests "<实际命令与结果>" `
  -Commit "<sha>" `
  -Evidence "<Gate 与证据路径>" `
  -NextStep "重算 Goal Gate 并执行下一 READY Task"
```

### 失败或暂停

必须立即记录：

- 被哪项证据否定或阻塞；
- 已完成哪些安全动作；
- 当前代码和数据状态；
- 唯一继续条件；
- 可执行的替代 Task；
- 是否还有其他无依赖 `READY` Task。

`PAUSED` 不是普通失败的替代品。能够通过改代码、修测试、修迁移、更新合同或修容器解决的问题不得记录为外部暂停。

### 查看断点

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation open
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation tail -Tail 30
```

---

## 6. 启动与中断恢复

每次开始或恢复 Goal：

1. 读取 `agent.md`；
2. 读取 Professional 七方案 README 的最新 Owner amendments；
3. 读取当前 Goal 文档和 Task Contract；
4. 运行 `control.ps1 -Operation open` 与 `tail`；
5. 运行：

```powershell
git status --short
git worktree list
git branch --all
git remote -v
git log -n 10 --oneline
```

6. 核对本地 `dev`、`origin/dev`、未推送提交、未提交 diff 与当前 HEAD；
7. 核对 Alembic head、OpenAPI/generated client、CI、当前 Task 证据；
8. 对未闭合 Task 追加真实状态，不盲目重做已经有效的证据；
9. 选择最高优先级 `READY` Task，继续执行循环。

恢复时优先保护用户和其他 Agent 的现有改动。不得用 reset、checkout 或 clean 覆盖未知改动。

---

## 7. 连续 Goal 执行循环

```text
恢复真实状态
→ 选择一个 READY Task
→ 确认/建立 Task Contract
→ 记录 STARTED
→ 实现最小范围
→ Focused Tests
→ Required Regression
→ Review Diff 与 Canonical Boundary
→ 更新合同、文档与证据
→ Commit
→ Push（按 Git 规则）
→ 记录 COMPLETED
→ 重算工作包与 Goal Gate
→ 自动执行下一 READY Task
```

完成以下任一事项都不得等待“继续”：

- 单个测试；
- 一次实现；
- 一个 Task；
- 一次 commit/push；
- 一个工作包；
- mock E2E；
- 旧候选 Gate。

Agent 只有在 `agent.md` 定义的外部阻塞条件成立时才能暂停。已由 Owner 授权的付费 Provider 调用不构成暂停条件。

若一个 Task 被外部条件阻塞，先记录 `PAUSED`，然后继续执行所有不依赖它的 `READY` Task。只有整个 Goal 无其他可执行路径时才报告 `GOAL_BLOCKED`。

---

## 8. 普通失败的自修复

以下问题默认由 Agent 自行处理：

- compile、lint、format、typecheck；
- unit、integration、Playwright；
- migration、RLS、schema、OpenAPI、generated client drift；
- Docker build、health、端口冲突；
- 依赖锁文件和可修复漏洞；
- Provider 请求的结构化校验失败；
- 测试 fixture 与当前合同不一致；
- Git 非破坏性冲突；
- CI 配置或 capability-aware Gate 错误；
- implementation 与 Task Contract 不一致。

自修复循环：

```text
复现
→ 确认根因
→ 最小修复
→ 失败路径测试
→ 回归
→ 更新证据
```

不得通过以下方式“修复”：

- 删除有效测试；
- 降低安全 Gate；
- 把 fail-closed 改成静默 fallback；
- 绕过 RLS、CSRF、版本或 Provider identity；
- hardcode 测试结果；
- 恢复 Legacy 兼容路径；
- 把真实失败改写成 skip；
- 用 dirty source 生成正式证据。

---

## 9. 主 Agent 与并行隔离

主 Agent 负责：

- 维护 Goal 状态和 Task 队列；
- 创建 bounded Task Contract；
- 分配 owned paths；
- 复核实现、测试、diff 和证据；
- 提交、push、创建或更新 PR；
- 每个 Task 后重算 Goal Gate；
- 到达 Owner 合并边界时生成最终交接。

默认串行执行。只有任务真正独立、依赖已满足、路径不重叠且执行环境允许时，才使用并行隔离任务。

并行规则：

- 只读任务可并行，但必须记录 `read_only=true`；
- 写入任务必须声明非空 `owned_paths`；
- 活动任务不得拥有重叠路径；
- 依赖关系明确的后续 Task 不提前派出；
- 同一文件尽量只归一个写入任务；
- subagent 汇报不是完成证据；
- 主 Agent 必须检查 commit、changed files、tests 与合同逐项结果；
- 合流后运行联合回归，再重算 Goal Gate。

---

## 10. Git、branch 与 worktree

### 日常串行 Task

```text
branch:   dev
worktree: repository root
remote:   push origin dev
```

### 并行隔离 Task

```text
branch:   agent/<task-id>
worktree: .worktrees/<task-id>
remote:   same branch + PR → dev
```

### Hotfix

```text
branch:   agent/hotfix-<task-id> from main
merge:    PR → main
followup: sync main fix back to dev
```

规则：

1. 根 worktree 保持在本地 `dev`；
2. 日常 Task 在 `dev` 提交并 push；
3. 并行隔离 Task 从当前本地 `dev` 创建；
4. `main` 禁止直接 push，只能通过受保护 PR；
5. 常规发布使用 `dev → main` PR，不用 cherry-pick 拼装发布；
6. Agent 不批准或合并自己的 PR；
7. 只有 `@zwb2002-yjy` 可以批准和合并；
8. Agent 不写 `MERGED` 记录；
9. 远端不可用时可继续本地提交并执行无远端依赖任务；
10. 禁止 force push、历史重写、`git reset --hard`、`git clean -fd`；
11. 禁止用 checkout 覆盖用户或其他 Agent 的未提交改动；
12. 只有确认隔离 PR 已合并且不再需要恢复时，才能移除 worktree 和分支。

创建隔离 worktree 使用仓库现有脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\task_worktree.ps1 `
  -Operation create `
  -TaskId <task-id> `
  -OwnedPaths "<paths>"
```

GitHub 保存共享的 branch/commit/PR/review/merge 历史；`PROGRESS.jsonl` 保存当前机器执行断点。两者不能互相替代。

---

## 11. Provider 调用纪律

Provider 权限范围以 `agent.md` 与最新 Owner amendment 为准。

当当前 Goal 已授权付费调用时：

- 不因费用暂停或重复询问；
- 使用项目现有已配置凭据；
- 不提取、复制或重用超出项目正常配置边界的凭据；
- 合并验证场景，减少无证据重复调用；
- 普通 unit/E2E 使用 deterministic/mock transport；
- 真实能力与最终 Golden 使用真实 Provider；
- 每次调用保留 ProviderOperation、model/binding identity、status、Artifact lineage；
- submit-unknown 或可能已经计费的请求不得盲目重试；
- secret、完整授权头和未脱敏响应不得进入日志、Git 或账本。

付费授权不允许 Agent：

- 绕过统一 Runtime；
- 私开 Provider HTTP；
- 自动 fallback 到其他模型；
- 重复消耗来掩盖实现缺陷；
- 声称未发生的调用或费用；
- 顺带建设计费、预算、账单或对账系统。

---

## 12. Task 验证与完成证据

### Focused Tests

每个 Task 至少验证：

- 用户可观察 Outcome；
- 主要失败路径；
- security/ownership；
- version/stale/idempotency；
- Canonical boundary；
- 明确 out-of-scope 未被突破。

### Cross-domain Regression

涉及跨域、迁移、公共类型或主链时，至少覆盖：

- Backend Ruff / Mypy / unit；
- PostgreSQL migration / integration / RLS / contract；
- OpenAPI export / generated client check；
- Frontend lint / typecheck / unit / build；
- Playwright；
- canonical surface；
- repository guardrails；
- 相关 Docker Gate。

### `COMPLETED` 条件

只有以下全部满足才能记录：

1. Task Outcome 已实现；
2. success criteria 全部通过；
3. focused tests 与 required regression 已运行；
4. diff 已复核，无越界改动；
5. migration/API/types/docs 同步；
6. evidence 路径有效；
7. commit 已创建；
8. Task Contract 与账本已更新；
9. 没有把未满足项隐藏为 warning/skip；
10. 下一 `READY` Task 已由 Goal Gate 计算。

---

## 13. Release Candidate 证据

最终发布候选必须从 exact-commit、干净 worktree 执行仓库当前权威 release runbook 与 Gate。

证据必须包含：

- `source_commit`；
- `dirty=false`；
- UTC 起止时间；
- migration head；
- 脱敏命令与环境摘要；
- image/source identity；
- Backend / PG / Frontend / Playwright / Security 结果；
- ProviderOperation 与 Artifact lineage；
- real Provider Golden；
- Final Film 与 Timeline/Formal Shot 来源；
- 运行期间 source 未变化。

遵循 `docs/runbooks/release-gate-board.md` 规定的证据目录和格式，不在本协议硬编码旧 P0 路径或旧文件名。

以下任一情况禁止报告 Release Candidate ready：

- `FAIL` 或未解释的 `BLOCKED`；
- dirty source；
- source/image/evidence mismatch；
- migration drift；
- required test 被 skip；
- Golden 绑定旧 commit；
- mock 被冒充真实 Provider；
- Final Artifact 无法追溯；
- secret 扫描失败。

旧候选或旧 Golden 只作历史证据，不能继承为当前 HEAD 结果。

---

## 14. Goal 交接状态

Goal 级状态用于最终回报，不新增 `PROGRESS.jsonl` 状态枚举。

### `GOAL_BLOCKED`

只有 `agent.md` 定义的真实外部阻塞成立、且没有其他可执行 `READY` Task 时使用。

必须报告：

- 最终 HEAD；
- 已完成工作包；
- 当前 blocked Task；
- 唯一外部继续条件；
- 已通过的 Gate；
- 未通过的 Gate；
- 恢复后第一动作。

### `GOAL_READY_FOR_OWNER_MERGE`

以下情况使用：

- Owner Goal 的实现和 1–20 项技术/产品 Gate 已满足；
- current-HEAD real Provider Golden 与 Final Film 完成；
- source、image、evidence 一致；
- `dev → main` PR 已具备完整证据；
- 唯一剩余动作是 Owner review/approve/merge。

Agent 此时不得自行批准或合并。

### `GOAL_DONE`

只有 Owner 完成必要批准/合并，且最终发布证据仍与合并候选一致时使用。

如果合并后 source SHA 改变并影响证据，先重新运行受影响 Gate，不能沿用合并前结果。

---

## 15. 最终回报

```text
STATE: GOAL_DONE | GOAL_READY_FOR_OWNER_MERGE | GOAL_BLOCKED

FINAL_HEAD:
MIGRATION_HEAD:
PR:

DELIVERED:

ARCHITECTURE_PROOF:
- one canonical product path
- one Project/Scene/Shot truth
- one Runtime
- one Artifact lineage
- one EditingAdapter
- legacy execution call = 0

VERIFICATION:
- backend
- PostgreSQL
- frontend
- Playwright
- security
- real Provider Golden
- Final Film
- deployment/health

EVIDENCE_PATHS:

REMAINING_OWNER_ACTION:
```

最终回报必须引用准确 commit、命令结果、Gate、真实 ProviderOperation 和证据路径，不能只叙述 Agent 做过什么。

---

## 16. 当前状态入口

本协议不写死某个一次性 Task、阶段标签或 Release Board。

当前状态以以下事实为准：

1. `agent.md` 的 Goal；
2. Professional 七方案 README 的最新 Owner amendments；
3. 当前 Task Contract；
4. `.agent-control/PROGRESS.jsonl`；
5. Git / CI / migration / tests / runtime evidence。

任何没有进入合同、账本、Git 或 commit-bound 证据的口头完成声明均不算完成。
