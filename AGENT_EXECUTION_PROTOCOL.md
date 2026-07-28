# DramaForge Agent 执行协议

**状态：强制执行**

**版本：v3.3**

**最近修订：2026-07-26**

## 1. 目的与边界

本协议为当前及未来所有开发任务规定三件事：

1. 每个 Task 在开始前先定义可观察的完成效果和验收证据，结束时在本地留下可恢复事实。
2. Agent 在普通失败后自行诊断、修复和回归；Task 完成后继续下一个 Task，阶段 Gate 通过后继续下一个阶段。
3. 日常写入在 `dev` 集成分支完成并推送；`main` 只接收经验证的稳定发布 PR。并行隔离或紧急修复才使用短期分支和独立 worktree；只有 `@zwb2002-yjy` 可以批准和合并受保护分支 PR。

完整的任务选择、自修复和阶段推进规则由 [`agent.md`](agent.md) 定义；本协议只规定记录语义、恢复方式和 Git 隔离。它不是调度器，也不判断哪个进程“拥有”仓库。项目不使用观察器、后台监控、Session、Token、心跳、进程数量门禁或恢复状态机。

## 2. Task 合同先于执行

任何 Task 写入 `STARTED` 前，必须先在 [`docs/开发执行检查点.md`](docs/开发执行检查点.md) 写出 Task 合同，至少包含：

- 唯一且稳定的 Task ID。
- 可由用户或测试观察的完成效果。
- 负责范围与明确非范围。
- 前置条件和外部依赖。
- 必须取得的验收证据。
- 预计改动模块或文件所有权。
- 可以写入 `COMPLETED` 的准确条件。

如果当前检查点没有可执行 Task，主 Agent 应根据当前阶段 Gate 创建一个最小、可验证、前置条件已满足的 `READY` Task，而不是等待用户逐项拆任务。

## 3. 本地进度账本

本地账本固定为：

```text
.agent-control/PROGRESS.jsonl
```

该文件只追加、不进入 Git。每行是一条独立 JSON 记录。控制脚本通过 Git common directory 定位主工作区，因此从关联 worktree 调用时仍写入同一份账本。脚本只提供三个动作：

- `log`：追加一条事实记录。
- `tail`：查看最近记录。
- `open`：查看每个 `task_id` 最后一条状态仍为 `STARTED` 或 `PAUSED` 的任务。

允许的状态及准确语义：

```text
STARTED   Task 合同已写明，执行已经开始
COMPLETED Task 完成效果和合同要求的全部验收证据均已满足
FAILED    当前方案已被证据否定，且已记录替代 Task、回滚或终止原因
PAUSED    Task 尚未完成，准确的外部继续条件已经记录
MERGED    用户已批准并确认进入 main，不代表所属阶段 Gate 已通过
```

阶段完成与 Task 完成严格分离。只有阶段的全部 Gate 和阶段级回归通过后，才能记录对应 `STAGE-<name>` 完成；单个 Task 的 `COMPLETED` 或 `MERGED` 不能代替阶段验收。

账本是只追加事实流。发现历史记录把“代码已写”误记为 `COMPLETED` 时，不得改写旧 JSONL；应对同一个 `task_id` 追加新的 `PAUSED`、`FAILED` 或其他符合当前事实的状态，并在 `summary`、`evidence` 和 `next_step` 中解释更正原因。`open` 只显示最后状态为 `STARTED` 或 `PAUSED` 的任务，因此状态更正后可以恢复到真实断点。

记录不得包含访问令牌、BYOK、密码、私钥、完整 Provider 响应、原始受限 fixture 或其他秘密。脚本的基础脱敏不能替代 Agent 的保密责任。

## 4. 标准记录方式

开始任务前记录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 `
  -Operation log `
  -Status STARTED `
  -TaskId S1-SESSION-0.1 `
  -Agent grok-subagent-session `
  -Summary "建立可验收的 Cookie 会话纵向切片" `
  -Branch dev `
  -Worktree . `
  -OwnedPaths "backend/app/access;backend/tests/integration/test_session_pg.py" `
  -NextStep "先运行会话未授权失败测试"
```

Task 合同全部通过后记录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 `
  -Operation log `
  -Status COMPLETED `
  -TaskId S1-SESSION-0.1 `
  -Agent grok-subagent-session `
  -Summary "Cookie 会话切片及未授权回归已通过" `
  -Branch dev `
  -Worktree . `
  -OwnedPaths "backend/app/access;backend/tests/integration/test_session_pg.py" `
  -ChangedFiles "backend/app/...;backend/tests/..." `
  -Tests "targeted pytest: passed; backend regression: passed" `
  -Commit "<sha>" `
  -Evidence "unauthorized=401;authorized=200" `
  -NextStep "推送 origin/dev；达到稳定发布条件时创建 dev -> main PR"
```

失败或暂停也必须立即记录，并在 `next_step` 中写清替代方案或唯一继续条件。Agent 不得自行记录 `MERGED`；`@zwb2002-yjy` 批准并合并 PR 后，由用户追加 `MERGED`，同时传入 `-ApprovedBy @zwb2002-yjy` 并记录 PR 与 merge commit。

查看最近记录和断点：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation tail -Tail 30
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation open
```

## 5. 连续执行与中断恢复

主 Agent 必须遵守 [`agent.md`](agent.md) 的持续开发控制循环：恢复事实、执行一个 `READY` Task、自修复、复核并提交到 `dev`；稳定发布合并后重算 Gate，然后继续同阶段下一 Task 或下一阶段合同任务。完成一个 Task、一个 subagent 批次或一次提交都不是等待“继续”的理由。

Agent 重启后按事实恢复：

1. 运行 `open` 和 `tail`，查看未闭合任务和最近状态更正。
2. 运行 `git status --short`、`git worktree list`、`git branch --all` 和 `git remote -v`。
3. 对每个未闭合任务检查 Task 合同、分支、worktree、最新 commit、未提交 diff 和测试结果。
4. 根据事实追加 `COMPLETED`、`FAILED` 或 `PAUSED`；不得依赖口头汇报，也不得盲目重跑已有证据的工作。
5. 读取开发检查点，选择最高优先级的 `READY` Task 并继续控制循环。

普通编译、测试、类型、迁移、依赖、进程退出、接口、数据、UI 和分支冲突由 Agent 按 `agent.md` 自行循环修复。只有真实外部输入、不可逆操作、受限权限或会改变产品路线的合同冲突才能暂停对应工作。一个外部 `PAUSED` Task 不阻止其他不依赖它的 `READY` Task。

## 6. 主 Agent 与 subagent

主 Agent 负责维护检查点、拆分 Task、分配文件所有权、指定分支/worktree、复核结果、创建或更新 PR，并在用户合并后重算阶段 Gate。subagent 只处理被分派的 Task 合同范围。

- 只读 subagent 可以并行，不需要分支或 worktree，但仍须留下开始和结束记录。
- 根 worktree 默认跟踪同步后的 `dev`，日常串行 Task 直接在其中提交并推送 `origin/dev`。
- 仅并行写入任务从同步后的 `dev` 创建独立 `agent/<task-id>` 分支和 `.worktrees/<task-id>`。这类任务的 `STARTED` 必须声明非空 `owned_paths`，且其他活动隔离任务不得声明重叠路径；只读任务必须显式记录 `read_only=true`。
- 远端可用时，日常 Task 推送 `dev`；隔离 Task 推送自己的分支并通过 PR 合回 `dev`。远端暂时不可用时保留提交并记录 `PAUSED`，不得直接推送 `main`。
- 同一文件尽量只分配给一个写入 subagent。确需交叉修改时，由主 Agent 负责冲突解决和合并后联合回归。
- subagent 的自然语言汇报不是完成证据。至少需要 commit、改动文件、实际测试结果和 Task 合同逐项结论。
- 主 Agent 不一次性派出具有依赖关系的后续 Task；用户每轮合并后重新计算 `READY` 队列和文件所有权。

## 7. Git 分支、worktree 与 GitHub

日常写入使用：

```text
branch:   dev
worktree: 仓库根 worktree
GitHub:   push origin dev
```

只有并行隔离任务使用：

```text
branch:   agent/<task-id>
worktree: .worktrees/<task-id>
GitHub:   同名远端分支 + PR -> dev
```

示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\task_worktree.ps1 `
  -Operation create `
  -TaskId s1-session-0.1 `
  -OwnedPaths "backend/app/access;backend/tests/integration/test_session_pg.py"
```

规则：

1. 根 worktree 必须保持在同步后的 `dev`；`main` 和 `origin/main` 只在准备发布或处理 hotfix 时同步。
2. 日常 Task 可直接在 `dev` 提交和推送。一个并行隔离 Task 才对应一个 `agent/<task-id>` 分支、一个 `.worktrees/<task-id>` 和一组不与活动隔离 Task 重叠的 `owned_paths`。
3. 提交、测试、发布 PR、用户批准、合并和清理都写入本地账本；Agent 只能记录到 `COMPLETED` 或 `PAUSED`。
4. `main` 只通过 `dev -> main` 的受保护 PR 接收稳定发布。本地 `.githooks/pre-push` 拒绝直接推送 `main`；GitHub Ruleset 必须要求固定 CI、Code Owner review 和 `@zwb2002-yjy` 的批准。
5. 紧急生产修复可从 `main` 创建 `agent/hotfix-<task-id>`，通过 PR 合入 `main` 后立即同步回 `dev`。常规发布不得用 cherry-pick 代替 `dev -> main` PR。
6. 远端或认证暂时不可用时，可继续在当前 `dev` 或隔离分支提交并记录 `PAUSED`，但不得直接推送 `main`。
7. Agent 不得批准或合并自己的 PR，也不得调用 `MERGED` 记录；只有 `@zwb2002-yjy` 完成批准和合并。
8. 禁止 force push、历史重写、`git reset --hard`、`git clean -fd` 和用 checkout 覆盖用户改动。
9. 用户确认隔离分支 PR 已合并且任务不再需要后，才能移除 worktree 和分支。

GitHub 保存团队共享的分支、提交、PR、审查和合并历史；`PROGRESS.jsonl` 保存当前机器上的执行断点。两者用途不同，不能互相替代。

正式发布或 P0 tag 前，必须从候选 commit 的干净 worktree 运行非 Docker WSL formal proof 和 §3.1 Gate。报告必须包含相同的 `source_commit`、`dirty=false`、UTC 起止时间、脱敏命令与环境摘要，并证明运行期间 source 未变化。任何 `FAIL`、`BLOCKED`、dirty 或 source mismatch 都禁止 `p0_mvp_complete=true`；生成报告只写入 `tmp/p0-evidence/<sha>/` 或仓库外路径，不刷新 tracked `docs/acceptance/*latest.json`。

## 8. 当前状态入口

本协议不写死 BOOT-0、S1 或任何一次性任务状态。当前产品阶段、工程 Gate、外部暂停项、`READY` 队列和唯一执行任务，以 [`docs/开发执行检查点.md`](docs/开发执行检查点.md) 为准。

检查点每次 Task 合并后必须更新。它应回答：现在在哪个阶段、哪条 Gate 已有证据、哪条尚未关闭、当前 Task 要产生什么可观察效果、完成后自动进入什么任务。没有记录到检查点、本地账本或 Git 的口头完成声明一律不算完成。
