# Task: P5-01 Experiment ORM（Phase 5 — Experiment / A-B）

## Status

- **State:** IN PROGRESS
- **Task id:** `p5-01-experiment-orm`
- **Program order:** Phase 4（P4-01…P4-11 + Golden Test 交付）→ **P5-01 Experiment ORM（本任务）** → P5-02 → …
- **Task boundary:** 新增 `ProductionExperiment` + `ShotExperiment` ORM 与迁移（project RLS）；不改既有 ExperimentBranch。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §45 Task P5-01
- 既有 `app/production/models.py`（ExperimentBranch）、迁移 0044 模式

## 依据（03 §45）

- 新增 `ProductionExperiment`、`ShotExperiment`；Migration 同步 RLS。

## Owned paths

- `backend/app/production/models.py`
- `backend/alembic/versions/20260827_0045_production_experiments.py`
- `backend/tests/unit/test_experiment_orm.py`
- `docs/plans/professional-program-v2/task-contracts/P5-01-EXPERIMENT-ORM.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P5-02 shot_experiment graph scope、P5-03 创建 API。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `ProductionExperiment`（project 级，idempotency_key 唯一）+ `ShotExperiment`（experiment+shot 唯一，含 source version/director state/prompts/references/model_overrides/common_controls/comparison/结果 artifact）。
- 迁移 `20260827_0045` 创建两表 + project RLS（FORCE）；`alembic upgrade head` 空库到 `20260826_0044`+0045 成功；downgrade 可用。
- ORM 测试：创建/关联/项目隔离；全量 unit 无回归；ruff/mypy 通过。
