# Task: P6-04/05/06 Manual Repair（Phase 6 — 审片、批注、修复）

## Status

- **State:** IN PROGRESS
- **Task id:** `p6-manual-repair`
- **Program order:** P6-02/03（COMPLETED）→ **P6-04/05/06 Manual Repair（本任务）** → Phase 6 Gate
- **Task boundary:** `POST .../repair-plan`（依据 annotations → repair option / affected nodes / retained assets / expected rerun scope）+ `POST .../repair`（Idempotency-Key；V1 仅 rerun_video / regenerate_keyframe_then_video；不做局部 inpaint）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §56/§57/§58

## Owned paths

- `backend/app/production/repair_service.py`
- `backend/app/api/v1/workbench.py`
- `backend/tests/unit/test_repair_service.py`
- `docs/plans/professional-program-v2/task-contracts/P6-MANUAL-REPAIR.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- 视频局部 inpaint / 秒替换 / smart continuation / 自动 splice。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `build_repair_plan`：根据 open ReviewAnnotations 返回 repair option / affected nodes / retained assets / expected rerun scope。
- `execute_repair`：rerun_video → 复用 WorkbenchExecutionService 派发 video NodeRun（正式关键帧）；regenerate_keyframe_then_video → 派发 keyframe 候选；Idempotency-Key 生效。
- 测试通过；全量 unit 无回归；ruff/mypy 通过。
