# RELEASE — 发布与分支保护权威

Status: current（入口见 [CURRENT.md](CURRENT.md)）

## Branch flow

- `main` 是受保护的稳定发布分支，禁止直接 push（本地 pre-push hook 与
  GitHub ruleset 双重拦截）。
- `dev` 是常规集成分支。日常修改通过短生命周期
  `agent/<task-id> -> dev` PR 集成；普通 PR 使用按变更风险分层的 CI，
  merge 到 `dev` 后不再原样重复同一套全量质量门。
- 发布的唯一正常方向：`dev -> main` PR。该 PR 必须执行完整质量与安全
  required checks；合并后本地 `main` fast-forward，并在历史分叉时把
  `main` 合回 `dev`。
- 短生命周期 `agent/<task-id>` 分支 + `.worktrees/<task-id>` 用于并行隔离
  工作：从 `dev` 出发、PR 目标 `dev`。生产 hotfix 可从 `main` 出发、
  目标 `main`，事后同步回 `dev`。
- Dependabot 常规版本更新当前暂停（各 ecosystem 的
  `open-pull-requests-limit: 0`）；安全告警保留人工分诊，自动安全修复关闭。
  恢复常规更新时只允许直接依赖、忽略 major 更新、使用
  `dependabot/* -> dev` PR，并在对应依赖审计与受影响质量门通过后由 Owner
  决定是否集成；不直接作为稳定版本更新合入 `main`。
- 只有 `@zwb2002-yjy` 批准 / 合并 PR；Agent 不自批、不自合、不记录 MERGED。

### 合并提交说明检查

获得本次合并授权后，合并前必须审阅最终提交的标题、正文、作者及署名 trailer。
Squash 必须显式传入审阅过的标题和正文，不使用自动拼接的全部分支历史；
`Co-authored-by` 仅保留身份和贡献均已核实、且本次确实需要的署名。
多行说明通过结构化 API 参数或 `--body-file` 传入。合并后再次读取远端实际
提交说明，确认没有无关历史、意外署名或工具生成文字，再继续合并下一项。

## Required GitHub ruleset（main）

当前 `main` ruleset 要求：

1. 禁止 force push 与分支删除；
2. required status checks 使用 strict 模式；
3. 精确要求：
   - `policy`
   - `container-gates`
   - `secret-scan`
   - `python-dependencies`
   - `frontend-dependencies`
   - `filesystem-scan`

`dev` ruleset 当前保留删除与 non-fast-forward 保护，不配置 required status
checks；`agent/* -> dev` 仍通过 CI workflow 做按风险分层验证。

PR CI 的分层规则见 [DEVELOPMENT.md](DEVELOPMENT.md)。`dev -> main` 不走
Fast Gate：上述六个 required checks 全部执行，其中 `container-gates`
包含 backend/frontend、PostgreSQL migration/integration、Playwright 与 LiteLLM
完整质量门。

Dependency Review 由仓库变量 `DEPENDENCY_REVIEW_ENABLED=true` 能力门控；
不可用时显式跳过。Python/Node 依赖审计、secret scan 与 Trivy filesystem scan
在 `dev -> main` 必须执行；周度完整安全扫描由
`.github/workflows/security.yml` 执行。

## 发布步骤

1. Check out the exact candidate SHA.
2. Run `scripts/run_quality_in_docker.ps1`（或 Linux 等价 Docker Compose 命令）.
3. Confirm Alembic reports a single head and that `alembic check` is clean
   （当前 head 记录在 [DATA_MODEL.md](DATA_MODEL.md)，以候选本身
   `alembic heads` 为准）.
4. Build release images from that same SHA with docker-compose.build.yml.
5. Start the release topology with docker-compose.yml.
6. Verify `/health`, `/gateway-health` and the source commit identity.
7. Open the frontend at http://127.0.0.1:8080.

Only the frontend gateway publishes a host port. The backend API port 8000 is
internal container networking and is not a second public entry.

The application path is Project → Story/Script → Scene/Shot → Workbench
Execution → Review/Repair → EditSession → Delivery, with proposal-only Director
assistance available alongside it. Retired Quick, Creation and controlled
Director paths are not supported and are not restored by release operations.

## Local setup

Install the tracked hooks once per clone:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_git_hooks.ps1
```

创建隔离并行任务 worktree（常规工作留在 `dev`）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\task_worktree.ps1 `
  -Operation create `
  -TaskId example-task `
  -OwnedPaths "backend/app/example;backend/tests/unit/test_example.py"
```

GitHub 是权威强制点（本地 hook 可被移除）。本地 `.agent-control` ledger 只是
审计数据，其 `approved_by` 不构成身份认证，不能替代 GitHub review 或受保护
分支合并记录。

## Release evidence

发布或 P0 tag 前，从 exact candidate commit 的干净 checkout 运行 Docker
Compose 正式证明。任何 FAIL / BLOCKED / dirty source / source mismatch 都
阻止发布。生成的报告默认写入 `tmp/p0-evidence/<sha>/`（不入 Git）。
