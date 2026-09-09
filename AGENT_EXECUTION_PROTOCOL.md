# DramaForge Agent 执行协议

**版本：v4.1 / 按任务加载。** 本文件规定执行边界；[agent.md](agent.md)负责区分只读、独立 Task 与已授权 Goal。产品依据与任务顺序仍由[七方案执行集及 Owner amendments](docs/plans/professional-program-v2/README.md)和当前合同决定。

## 合同与范围

- 实施前建立或确认 [bounded Task Contract](docs/plans/professional-program-v2/task-contracts/)：Current Evidence / Drift、Outcome、owned paths、非范围、success criteria、focused tests、required regression、操作授权与完成证据。只读问答/审计不进入实施生命周期。
- 一次只推进当前有依赖依据的 bounded Task；修复本次改动导致的问题，不顺手扩大产品范围或改写预期来消除测试失败。
- 独立任务在 Outcome 和所需验证完成后结束。已授权 Goal 则继续重算 Gate 与 READY，不在单个 Task/commit/push 后无故停下；仅在整个 Goal 无安全可执行路径或到达 Owner 专属边界时交接。

## 恢复、账本与操作明细

- 仅在恢复已有 Task/Goal 或核验其状态时读取相关合同、Git 和账本事实；不为每次只读会话固定枚举所有分支、remote、migration 或 CI。
- 需要记录状态时使用 [.agent-control/control.ps1](.agent-control/control.ps1) 的实际参数；账本只追加、不入 Git、不含 secret。STARTED、COMPLETED、FAILED、PAUSED、MERGED 语义不混用；Agent 不写 MERGED。
- [按需操作明细](docs/runbooks/agent-instructions/execution-protocol-reference.md)：§3–5 为合同/账本参数，§6–8 为 Goal 恢复/自修复，§9–10 为隔离/Git，§11 为 Provider，§12 为验证，§13–16 为发布/交接。仅读取所需章节。
- 普通可修复失败在当前授权与 owned paths 内诊断、修复、复测；新增产品决定、生产/费用授权或不可逆操作边界不能由“持续执行”越过。

## 验证与证据

- 以 Task Outcome、失败路径及实际受影响的安全/版本/幂等/跨域边界选择验证。不把全仓库的所有检查当作每个改动的默认循环；合同要求的 required regression 和正式 Gate 不减少。
- 命令事实取自 [frontend/package.json](frontend/package.json)、[backend/pyproject.toml](backend/pyproject.toml)、[当前 CI](.github/workflows/ci.yml)和[容器质量配置](docker-compose.quality.yml)。明确执行目录及选择条件，不复制旧 script/job 清单或擅自替换 smoke 语义。
- 真实 PostgreSQL、RLS/迁移、generated client、端到端或真实 Golden 是否必需，由当前变更和合同决定；必需验证不能用 SQLite、mock 或 skip 冒充。
- 正式 Task COMPLETED 仍需满足合同、实际验证、复核 diff、有效证据、commit 和状态记录等条件；独立 Task 不必虚构“下一 READY Task”。未提交的本地实现如实报告为已实现/已验证、尚未提交，不伪写正式 COMPLETED。
- Release Candidate 必须符合当前合同指定的 exact-commit、干净 source、镜像身份、Gate、真实 ProviderOperation / Artifact lineage 和 Final Film 条件。旧 Release Board/旧 Golden 不提供当前发布权威。
- 图像、截图和受限证据始终遵守 [AGENTS.md](AGENTS.md)；保留原始证据，不以清理名义删除历史产物。

## Git、权限与交接

- 日常集成仍在 dev；已授权 Goal 沿用既定 commit/push 流程。独立任务的提交、推送和 PR 依当前请求/合同，不把一次实现请求扩大为远端发布授权。
- main 不直接 push；常规发布为 dev → main。保留协议明细中的隔离 Task / hotfix 分支例外，使用现有 worktree 脚本且不覆盖已有改动。
- 默认串行。只有用户或适用指令明确授权委派、任务独立且 owned paths 不重叠时才隔离并行；运行条件不等于委派授权。
- 只有 @zwb2002-yjy 批准/合并；Agent 不自批、自合或记录 MERGED。不 force push、重写历史、reset --hard、clean -fd，也不以 checkout 覆盖用户改动。
- 清理仅限本任务资源；worktree/分支只有在隔离 PR 已合并且不再需要恢复时才能移除。保留生产、凭据与费用授权边界，可能已生效的操作不盲目重试。
- 回报当前请求的 Outcome、实际验证、证据与剩余边界；只有连续 Goal 使用 GOAL_BLOCKED / GOAL_READY_FOR_OWNER_MERGE / GOAL_DONE，独立任务不冒充 Goal 或发布完成。
