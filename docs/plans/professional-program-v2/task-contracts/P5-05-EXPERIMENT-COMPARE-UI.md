# Task: P5-05 Experiment Compare UI（Phase 5 — Experiment / A-B）

## Status

- **State:** COMPLETE
- **Task id:** `p5-05-experiment-compare-ui`
- **Program order:** P5-04（COMPLETED）→ **P5-05 Experiment Compare UI（本任务）** → P5-06 → …
- **Task boundary:** `ExperimentCompare.tsx` 对比列（正式 / 实验A / 实验B）：image、video、model、prompt、translation warning、references。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §49 Task P5-05

## 依据（03 §49）

- 新增 `ExperimentCompare.tsx`；默认正式 / 实验 A / 实验 B。
- 可比较：image、video、model、prompt、translation warning、references。

## Owned paths

- `frontend/src/features/experiments/ExperimentCompare.tsx`
- `frontend/tests/unit/ExperimentCompare.test.tsx`
- `docs/plans/professional-program-v2/task-contracts/P5-05-EXPERIMENT-COMPARE-UI.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P5-06 adopt API。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `ExperimentCompare` 按行渲染 image/video/model/prompt/translation warning/references；无 provider/model 名分支。
- vitest 测试通过；tsc/build/eslint 通过。
