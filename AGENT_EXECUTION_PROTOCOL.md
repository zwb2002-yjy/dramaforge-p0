# DramaForge Agent 执行协议

**状态：强制执行**  
**版本：v3.0**  
**最近修订：2026-07-20**

## 1. 目的

本协议只解决两个问题：

1. Agent 或 subagent 做了什么、做到哪里，必须在本地留下可读记录。
2. 多个写入 Agent 通过 Git 分支、GitHub 和独立 worktree 隔离，不能同时修改同一个工作区。

它不是调度器，也不判断哪个进程“拥有”仓库。项目不使用观察器、后台监控、Session、Token、心跳、进程数量门禁或恢复状态机。

## 2. 本地进度账本

本地账本固定为：

```text
.agent-control/PROGRESS.jsonl
```

该文件只追加、不进入 Git。每一行是一条独立 JSON 记录。脚本会通过 Git common directory 定位主工作区，因此从任何关联 worktree 调用时仍写入同一份账本。控制脚本只提供三个动作：

- `log`：追加一条记录。
- `tail`：查看最近记录。
- `open`：查看最后状态仍为 `STARTED` 或 `PAUSED` 的任务。

允许的状态只有：

```text
STARTED
COMPLETED
FAILED
PAUSED
MERGED
```

每个可独立分派的工作必须使用唯一 `task_id`。例如：

```text
BOOT-0.1
BOOT-0.1/backend-shell
BOOT-0.1/frontend-shell
```

记录包含时间、任务、Agent、状态、摘要、分支、worktree、改动文件、测试、commit、证据和下一步。不得写入访问令牌、BYOK、密码、私钥、完整 Provider 响应或其他秘密；脚本会做基础脱敏，但不能替代 Agent 的保密责任。

控制脚本在追加单行时会短暂独占日志文件，避免两个进程把同一行写坏。这个毫秒级文件锁只保护 JSONL 写入，不代表任务所有权，也不会阻止其他 Agent 开发。

## 3. 标准记录方式

开始任务前记录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 `
  -Operation log `
  -Status STARTED `
  -TaskId BOOT-0.1/backend-shell `
  -Agent grok-subagent-backend `
  -Summary "建立后端项目骨架" `
  -Branch agent/boot-0.1-backend `
  -Worktree .worktrees/boot-0.1-backend `
  -NextStep "创建 FastAPI health 路由"
```

完成任务后立即记录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 `
  -Operation log `
  -Status COMPLETED `
  -TaskId BOOT-0.1/backend-shell `
  -Agent grok-subagent-backend `
  -Summary "后端骨架和健康检查完成" `
  -Branch agent/boot-0.1-backend `
  -Worktree .worktrees/boot-0.1-backend `
  -ChangedFiles "backend/pyproject.toml;backend/app/main.py" `
  -Tests "pytest: passed" `
  -Commit "<sha>" `
  -NextStep "主 Agent 审查并创建或更新 PR"
```

失败或暂停同样要立即记录，并在 `next_step` 中写清继续条件。任务合并到 `main` 后，主 Agent追加 `MERGED`，记录 PR、merge commit 或等价证据。

查看最近记录和中断点：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation tail -Tail 30
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agent-control\control.ps1 -Operation open
```

`open` 只根据每个 `task_id` 的最后一条状态判断。发现未闭合的 `STARTED` 或 `PAUSED` 后，先检查其分支、worktree、commit、diff 和测试，再决定继续、失败或完成；不要盲目重跑。

## 4. 主 Agent 与 subagent

主 Agent 负责拆分任务、指定分支和 worktree、复核结果并合并。subagent 只处理被分派的范围。主 Agent 在派出前记录任务和分支；subagent 启动后自行记录 `STARTED`，返回前自行记录 `COMPLETED`、`FAILED` 或 `PAUSED`，避免执行过程只存在于主 Agent 的聊天上下文。

- 只读 subagent 可以并行，不需要分支或 worktree。主 Agent 在派出前记录 `STARTED`，收到结论后记录 `COMPLETED`、`FAILED` 或 `PAUSED`。
- 写入 subagent 必须使用独立分支和独立 worktree。不能让多个写入 Agent 共用仓库根目录。
- 每个写入 subagent 在自己的分支提交改动，并将分支推送到 GitHub。不得直接推送 `main`。
- 主 Agent必须检查 diff、测试和冻结合同，再通过 PR 或明确的本地合并顺序进入 `main`。
- 分支不能消除逻辑冲突。同一文件最好只分给一个 subagent；确需并行修改时，由主 Agent承担后续冲突解决和联合测试。
- subagent 的自然语言汇报不是完成证据。至少要有 commit、改动文件和测试结果；主 Agent复核后再写 `MERGED`。

## 5. Git 分支、worktree 与 GitHub

仓库有基线提交后，写入任务采用以下结构：

```text
branch:   agent/<task-id>
worktree: .worktrees/<task-id>
GitHub:   同名远端分支 + PR
```

示例：

```powershell
git worktree add .worktrees/boot-0.1-backend -b agent/boot-0.1-backend main
git -C .worktrees/boot-0.1-backend push -u origin agent/boot-0.1-backend
```

规则：

1. 初始基线提交之前，只允许并行只读；写入必须串行，因为尚无可供 worktree 分叉的提交。
2. 一个写入 subagent 对应一个分支和一个 worktree。
3. 分支创建、首次推送、PR、测试结果、合并和清理都要写入本地账本。
4. GitHub 私有仓库、`origin` 和认证未核验前不得推送。不得把访问令牌写入 remote URL、文件、日志或命令记录。
5. 禁止 force push、历史重写、`git reset --hard`、`git clean -fd` 和用 checkout 覆盖用户改动。
6. 合并成功并确认不再需要后，才能移除 worktree 和分支；清理结果记录为 `MERGED` 的证据或后续记录。

GitHub 保存分支、提交、PR、审查和合并历史，是团队共享事实；`PROGRESS.jsonl` 保存当前机器上的执行断点，是本机事实。二者用途不同，不能互相替代。

## 6. 中断恢复

没有心跳和自动接管。Agent 重启后只做以下检查：

1. 运行 `open` 查看未闭合任务。
2. 运行 `git status --short`、`git worktree list` 和 `git branch --all`。
3. 对每个未闭合任务检查对应 worktree、分支、最新 commit、未提交 diff 和测试结果。
4. 根据事实追加 `COMPLETED`、`FAILED` 或 `PAUSED`，再继续工作。

没有记录到本地或 Git 的口头完成声明一律不算完成。

## 7. BOOT-0 当前状态

DramaForge 当前没有初始提交、没有远端配置，也没有 `frontend/`、`backend/` 或 `docker-compose.yml`。`BOOT-0.1` 应用开发尚未开始。

第一位写入 Agent 先在主工作区串行完成并提交基线。只有基线提交存在且 GitHub 私有远端核验完成后，后续写入 subagent 才能按本协议并行创建分支、worktree 和 PR。
