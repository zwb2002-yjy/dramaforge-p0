# Task: P7-02 DirectorThread / DirectorMessage（Phase 7 — 导演智能体 Copilot）

## Status

- **State:** IN PROGRESS
- **Task id:** `p7-02-director-thread`
- **Program order:** P7-01（COMPLETED）→ **P7-02 DirectorThread / DirectorMessage（本任务）** → P7-03 → …
- **Task boundary:** `DirectorThread`（scope project/scene/shot）+ `DirectorMessage` ORM 与迁移（project RLS）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §62 Task P7-02

## Owned paths

- `backend/app/director/models.py`（或新建）
- `backend/alembic/versions/20260827_0047_director_threads.py`
- `backend/tests/unit/test_director_thread.py`
- `docs/plans/professional-program-v2/task-contracts/P7-02-DIRECTOR-THREAD.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- DirectorThread scope_type ∈ project/scene/shot + project RLS；DirectorMessage 挂 thread、role user/assistant。
- 迁移 0047 空库到 head 成功；ORM 测试通过；全量 unit 无回归；ruff/mypy 通过。
