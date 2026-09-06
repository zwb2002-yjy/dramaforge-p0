# Task: Phase 6 Gate（03 §59 验收）

## Status

- **State:** COMPLETE
- **Task id:** `p6-gate`
- **Program order:** P6-01…P6-06（COMPLETED）→ **Phase 6 Gate（本任务）** → Phase 7
- **Task boundary:** 证明 §59 E2E：视频 2.3–3.1s 人物漂移标注 → Repair Plan → 重做关键帧后整段视频 → 新 Keyframe candidate → 用户确认 → 新视频 → 旧正式结果仍在历史。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §59 Phase 6 Gate

## Owned paths

- `backend/tests/unit/test_phase6_gate.py`
- `docs/plans/professional-program-v2/task-contracts/P6-GATE.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- Gate 测试覆盖 §59 全流程并通过；旧正式结果保留历史；全量 unit 无回归；ruff/mypy 通过。
