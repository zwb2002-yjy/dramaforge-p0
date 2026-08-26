# Task: P5-03 Create Experiment API（Phase 5 — Experiment / A-B）

## Status

- **State:** IN PROGRESS
- **Task id:** `p5-03-create-experiment-api`
- **Program order:** P5-02（COMPLETED）→ **P5-03 Create Experiment API（本任务）** → P5-04 → …
- **Task boundary:** `POST /projects/{id}/experiments`：单 shot 复制 shot version / director state / prompts / references / common model settings 为 ShotExperiment；场景为指定 Shot 批量创建 ShotExperiment。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §47 Task P5-03

## 依据（03 §47）

- API `POST /projects/{project_id}/experiments`。
- 单 Shot：复制 shot version、director state、prompts、references、common model settings。
- 场景：为 Scene 下所有指定 Shot 创建 ShotExperiment。

## Owned paths

- `backend/app/production/experiment_service.py`
- `backend/app/api/v1/experiments.py`
- `backend/tests/unit/test_experiment_service.py`
- `docs/plans/professional-program-v2/task-contracts/P5-03-CREATE-EXPERIMENT-API.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P5-04 model swap 语义、P5-05 compare UI、P5-06 adopt。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- 单 shot 创建：ShotExperiment 快照含 shot version/director_state/prompts/references/common_controls；不动正式 Shot。
- 场景创建：scene_id 下指定 shots 全部创建；idempotency_key 去重。
- API 测试通过；全量 unit 无回归；ruff/mypy 通过。
