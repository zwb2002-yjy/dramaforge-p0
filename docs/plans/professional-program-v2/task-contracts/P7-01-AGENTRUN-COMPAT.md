# Task: P7-01 AgentRun Compatibility（Phase 7 — 导演智能体 Copilot）

## Status

- **State:** IN PROGRESS
- **Task id:** `p7-01-agentrun-compat`
- **Program order:** Phase 6（COMPLETED）→ **P7-01 AgentRun Compatibility（本任务）** → P7-02 → …
- **Task boundary:** `agent_runs.planning_authorization_id` 改 nullable；`agent_operation` 枚举加 `director_assist`；旧路径（skill_execute 等）仍要求 Planning Authorization；新 Assistant 不要求 Budget Authorization。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §61 Task P7-01

## Owned paths

- `backend/app/creation/models.py`
- `backend/alembic/versions/20260827_0046_agentrun_director_assist.py`
- `backend/tests/unit/test_agentrun_compat.py`
- `docs/plans/professional-program-v2/task-contracts/P7-01-AGENTRUN-COMPAT.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- `director_assist` 枚举值存在；`planning_authorization_id` nullable。
- director_assist AgentRun 可在无 planning_authorization 时创建；skill_execute 仍要求。
- 迁移 0046 空库到 head 成功；全量 unit 无回归；ruff/mypy 通过。
