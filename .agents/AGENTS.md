# DramaForge Agent 开发执行规范

**版本**：1.1
**适用仓库**：`D:\调研\dramaforge`
**生效前提**：与 `AGENT_EXECUTION_PROTOCOL.md`、`agent.md`、`docs/开发执行检查点.md` 共同构成 Agent 执行合同。发生冲突时，以 `AGENT_EXECUTION_PROTOCOL.md` 和 `agent.md` 为准。

---

## 1. 总则

1. 日常项目改动以 **Task** 为单位管理，在 `dev` 分支提交并推送。稳定发布只通过 `dev -> main` 的 GitHub PR 进入 `main`。
2. **禁止直接推送 `main`**。本地 hook 会拒绝 `git push origin main`。
3. 仓库根工作区默认跟踪 `dev`，承载日常串行开发；`main` 只用于发布核验、hotfix 基线和同步。
4. 仅并行隔离 Task 使用独立 `agent/<task-id>` 分支、独立 worktree 和不重叠的 `owned_paths`；其 PR 目标为 `dev`。
5. Agent 可以提交、推送、创建 PR、复核 diff，但 **不得批准、合并或记录 `MERGED`**。只有 `@zwb2002-yjy` 能执行这些动作。
6. 每次会话开始时必须先恢复事实：运行 `.agent-control/control.ps1 -Operation open` 和 `tail -Tail 20`，并检查 `git status --short`、`git worktree list`、`git branch --all`、`git remote -v`。

---

## 2. Task 生命周期

一次改动的标准流程：

```text
在 docs/开发执行检查点.md 写 Task 合同
  → 日常 Task 在同步后的 dev 实现；并行 Task 用 scripts/task_worktree.ps1 创建 agent/<task-id> 分支和 .worktrees/<task-id>
  → .agent-control/control.ps1 append STARTED
  → 在 dev 根 worktree（或并行任务的独立 worktree）中实现、测试、自审
  → git add 本 Task 文件；git commit；git push origin dev
  → 稳定发布时创建 GitHub PR（目标 main，来源 dev）
  → CI 全绿 + 用户批准后由用户合并稳定发布 PR
  → 用户写 MERGED 到 .agent-control/PROGRESS.jsonl
  → 清理本地/远端任务分支和 worktree
  → 更新 docs/开发执行检查点.md 为下一阶段唯一任务
```

### 2.1 Task 合同模板

每个 Task 在 `docs/开发执行检查点.md` 必须包含：

```text
Task ID：唯一且稳定
状态：IN_PROGRESS / COMPLETED / PAUSED / FAILED
完成效果：用户能完成什么，或哪个运行时不变量得到证明
范围：本 Task 负责和明确不负责什么
前置条件：依赖的 Gate、迁移、fixture、服务和外部授权
验收证据：必须执行的测试、演练、截图/产物或哈希
预计改动：模块与文件所有权，供并行隔离使用
完成定义：什么情况下可以写 COMPLETED
非范围：明确不开发的能力
```

### 2.2 状态语义

写入 `.agent-control/PROGRESS.jsonl` 时严格区分：

| 状态 | 含义 | 谁能写 |
|---|---|---|
| `STARTED` | Task 开始 | Agent |
| `COMPLETED` | Task 合同中的完成效果和全部验收证据已满足 | Agent |
| `PAUSED` | 外部条件阻塞，已记录准确继续条件 | Agent |
| `FAILED` | 当前方案经证据证明不可行，需替代 Task 或回滚 | Agent |
| `MERGED` | 用户已批准并确认进入 `main`；必须带 `ApprovedBy @zwb2002-yjy` | **只有用户** |

---

## 3. 分支与工作区规范

### 3.1 分支命名

- 日常集成分支：`dev`。
- 稳定发布分支：`main`。
- 并行隔离分支：`agent/<task-id>`，例如 `agent/REPO-GUARDRAILS-BOOTSTRAP`。
- 紧急生产修复：`agent/hotfix-<task-id>`，从 `main` 创建、合回 `main` 后立即同步到 `dev`。

### 3.2 worktree 创建

使用项目提供的脚本：

```powershell
scripts/task_worktree.ps1 -TaskId <task-id> [-OwnedPaths <paths>]
```

脚本会校验：
- 当前在 `dev` 分支的 worktree；
- `dev` 与 `origin/dev` 同步；
- 该 Task 的 `owned_paths` 不与其他 `IN_PROGRESS` 或 `STARTED` 的 Task 重叠。

### 3.3 根工作区规则

- 仓库根目录（`D:\调研\dramaforge`）默认检出 `dev` 并承载日常业务修改。
- 需要并行写入隔离时，才进入 `.worktrees/<task-id>`。
- `main` 只用于稳定发布核验、hotfix 基线和同步，不承载日常开发。

### 3.4 禁止的 Git 操作

以下操作除非用户明确授权，否则禁止执行：

- `git push origin main`
- `git reset --hard`
- `git clean -fd`
- `git checkout -- <file>` 作为清理手段
- `git push --force` / `git push -f`
- `git rebase -i` 重写已推送历史
- 未审查的自动合并

---

## 4. 提交规范

### 4.1 提交纪律

- 一个提交只对应一个可验证 Task；不要把整个阶段塞进一个提交。
- 提交前运行 `git diff --stat` 和 `git diff --check`。
- 只暂存本 Task 的文件，不包含既有用户改动或其他 Task 的变更。
- 提交信息格式：

```text
<task-id>: <动词> <对象>

- 做了什么
- 为什么做
- 验证了什么
```

例如：

```text
REPO-GUARDRAILS-BOOTSTRAP: add branch/worktree guardrail script

- Create scripts/task_worktree.ps1 to enforce agent/* branches.
- Validate origin/main sync and owned_paths overlap before creating worktree.
- Add repo_guardrails.py for state transition and CODEOWNERS rules.
```

### 4.2 禁止提交的内容

- 密钥、Token、密码、私钥
- 真实用户数据或真实 Provider 响应
- Embedding、完整提示词/响应
- 永久对象 URL
- 构建产物：`dist/`、`__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`
- 测试临时文件和 dirty evidence
- 未说明的 vendor 二进制

---

## 5. PR 流程

### 5.1 PR 来源与目标

- 常规稳定发布 PR 的目标必须是 `main`，来源必须是 `dev`。
- 并行隔离 Task 的 PR 目标必须是 `dev`，来源必须是 `agent/<task-id>`。
- 紧急 hotfix PR 可从 `agent/hotfix-*` 目标 `main`，且合并后必须同步到 `dev`。

### 5.2 PR 模板

创建 PR 时必须使用 `.github/pull_request_template.md`，填写完整：

```markdown
## Scope
- Task ID:
- Owned paths:
- User-visible result:

## Verification
- [ ] policy
- [ ] backend-static
- [ ] backend-unit
- [ ] postgres-integration
- [ ] frontend
- [ ] frontend-smoke
- [ ] frontend-smoke-windows
- [ ] No generated formal evidence was committed from a dirty worktree.
- [ ] The PR follows the `dev -> main`, `agent/<task-id> -> dev`, or `agent/hotfix-* -> main` flow.

## Approval
- [ ] `@zwb2002-yjy` has reviewed and approved this PR.
- [ ] The author/agent did not approve or merge its own changes.
```

### 5.3 审查与合并

- CODEOWNERS 规定 `* @zwb2002-yjy`，所有改动都需要 `@zwb2002-yjy` review。
- Agent 不能批准自己的 PR，不能合并。
- 用户合并后，由用户追加 `MERGED` 记录到 `.agent-control/PROGRESS.jsonl`。

---

## 6. CI 门禁

PR 合并前必须通过 `.github/workflows/ci.yml` 定义的全部 job：

| Job | 检查内容 | 是否阻塞 |
|---|---|---|
| `policy` | 仓库策略、目录合规、guardrail 检查 | 是 |
| `backend-static` | Ruff、mypy、isort 等后端静态检查 | 是 |
| `backend-unit` | 后端单元测试 | 是 |
| `postgres-integration` | 真实 PostgreSQL 集成测试 | 是 |
| `frontend` | ESLint、Prettier、tsc --noEmit、Vitest、build | 是 |
| `frontend-smoke` | Playwright smoke 测试 | 是 |
| `frontend-smoke-windows` | Windows Playwright smoke 测试 | 是 |

### 6.1 特殊要求

- `postgres-integration` 必须跑真实 PostgreSQL，**不可用 SQLite 替代**。
- 真实 PG 测试不可静默 skip；Worker 并发、幂等、取消等关键行为必须在此覆盖。
- 生成正式证据时，工作树必须是干净的；dirty evidence 禁止提交或作为完成证明。

---

## 7. 本地账本 `.agent-control/PROGRESS.jsonl`

### 7.1 工具

```powershell
# 恢复断点
.agent-control/control.ps1 -Operation open

# 查看最近 20 条
.agent-control/control.ps1 -Operation tail -Tail 20

# 追加记录
.agent-control/control.ps1 -Operation append `
  -TaskId <task-id> `
  -Status <STARTED|COMPLETED|PAUSED|FAILED> `
  -Message "..." `
  -Branch agent/<task-id> `
  -Worktree .worktrees/<task-id> `
  -OwnedPaths "path1,path2" `
  -Evidence "..."
```

### 7.2 每次会话开始必须执行

1. 核验当前目录为 `D:\调研\dramaforge`。
2. `.agent-control/control.ps1 -Operation open`
3. `.agent-control/control.ps1 -Operation tail -Tail 20`
4. `git status --short`
5. `git worktree list`
6. `git branch --all`
7. `git remote -v`

### 7.3 记录规范

- 每次状态变更必须追加一行 JSONL，不能只改内存。
- `COMPLETED` 必须附带验收证据。
- `PAUSED` 必须附带准确继续条件。
- `FAILED` 必须附带失败原因和下一步方案。
- `MERGED` 只能由用户写入，并注明 `ApprovedBy @zwb2002-yjy`。

---

## 8. 多 subagent 规范

### 8.1 主 Agent 职责

- 为每个委派分配唯一 `task_id`。
- 记录 subagent 目标分支、worktree、`owned_paths` 和验收命令。
- 检查 diff、测试、合同后创建或复核 PR。
- 解决多个分支修改同一文件时的冲突。
- 用户合并后运行联合回归测试。

### 8.2 subagent 职责

- 只读 subagent 可以并行，不需要 worktree，但仍须记录 `STARTED` 和结束状态。
- 并行写入 subagent 必须使用独立 `agent/<task-id>` 分支和 `.worktrees/<task-id>`。
- subagent 在自己的分支提交并推送，PR 合入 `dev`；日常主开发直接在 `dev` 提交并推送。两者都不得直接修改或推送 `main`。
- subagent 返回时须提供：改动文件、测试命令与结果、commit SHA、已知阻塞。

### 8.3 并行限制

- 多个写入 Task 并行时，`owned_paths` 不得重叠。
- 主 Agent 每轮合并后重新计算下一批 `READY` Task，不要把所有任务一次性派出。
- 同一文件被多个 Task 修改时，由主 Agent 负责合并冲突和联合测试。

---

## 9. 合并后清理清单

稳定发布 PR 合并到 `main` 后，按顺序执行：

1. 切回根工作区并拉取最新 `main`：
   ```powershell
   cd D:\调研\dramaforge
   git checkout main
   git pull origin main
   git checkout dev
   git merge main
   git push origin dev
   ```
2. 删除本地任务分支：
   ```powershell
   git branch -d agent/<task-id>
   ```
3. 删除远端任务分支：
   ```powershell
   git push origin --delete agent/<task-id>
   ```
4. 移除 worktree：
   ```powershell
   git worktree remove .worktrees/<task-id>
   # 如目录残留再手动删除
   ```
5. 更新 `docs/开发执行检查点.md`：
   - 把当前 Task 标为完成；
   - 写入下一阶段唯一执行任务。
6. 由用户在 `.agent-control/PROGRESS.jsonl` 追加 `MERGED` 记录。
7. 如该 Task 是阶段最后一个 Gate，运行阶段级回归并写阶段验收记录。

---

## 10. 人工阻塞条件

以下情况 Agent 必须停止控制循环并请求用户：

1. 需要真实 BYOK、付费 Provider、购买额度或登录外部账号。
2. 需要下载安装依赖但网络/系统权限受限，本地无可用替代。
3. 需要在外部应用或硬件中完成不可自动化的真实验收。
4. 冻结合同存在无法由优先级规则消解的冲突，且会改变产品效果/数据合同/长期架构。
5. 需要删除用户数据、重写 Git 历史、覆盖既有改动或其他不可逆操作。
6. 缺少只有用户能提供的受限 fixture、账号、许可证或商业决定，且阻断所有剩余 `READY` Task。

**以下情况不属于人工审批事项，Agent 应自主解决：**
本地编码、测试失败、质量脚本、开发服务、mock、迁移、普通依赖冲突、分支冲突、文档同步、阶段任务拆分。

---

## 11. 质量门禁命令

开发中应频繁运行：

```powershell
# 后端静态
ruff check backend
mypy backend

# 后端单元
cd backend
pytest tests/unit

# 后端真实 PG 集成（需本地 PG+Redis 栈）
pytest tests/integration

# 前端静态
cd frontend
npm run lint
npm run format:check
npm run typecheck

# 前端测试与构建
npm run test
npm run build

# Playwright smoke
npm run test:smoke
```

---

## 12. 快速检查表

每次提交 PR 前对照：

- [ ] Task ID 在分支名、提交信息、PR、账本中一致。
- [ ] 改动范围与 Task 合同一致，无顺手开发的其他阶段能力。
- [ ] 只修改了本 Task 文件，无既有用户改动混入。
- [ ] `git diff --check` 无空白错误。
- [ ] 后端 Ruff、mypy 通过。
- [ ] 后端单元测试通过。
- [ ] 真实 PostgreSQL 集成测试通过（未 skip）。
- [ ] 前端 lint、typecheck、Vitest、build 通过。
- [ ] Playwright smoke 通过。
- [ ] 没有提交密钥、真实数据、构建产物、临时文件。
- [ ] 日常改动已推送 `dev`；稳定发布 PR 为 `dev -> main`，或隔离/hotfix PR 使用允许的例外流向，模板填写完整。
- [ ] 已创建/更新 PR，等待 `@zwb2002-yjy` review。
- [ ] `.agent-control/PROGRESS.jsonl` 已追加 `COMPLETED`。

---

## 13. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| 1.0 | 2026-07-23 | 建立 DramaForge Agent 改动管理、分支、提交、PR、CI、账本和 subagent 规范。 |
| 1.1 | 2026-07-26 | 改为 dev 日常集成、main 稳定发布，短期 agent 分支只用于并行隔离或 hotfix。 |
