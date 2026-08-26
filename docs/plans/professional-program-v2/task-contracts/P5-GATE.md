# Task: Phase 5 Gate（03 §51 验收）

## Status

- **State:** IN PROGRESS
- **Task id:** `p5-gate`
- **Program order:** P5-01…P5-06（COMPLETED）→ **Phase 5 Gate（本任务）** → Phase 6
- **Task boundary:** 用 Phase 5 实现证明 03 §51 六项：实验不覆盖正式；换模型不复制 raw payload；A/B 可并存；可部分采纳；旧正式保留历史血缘；场景实验可只采纳某些 Shot。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §51 Phase 5 Gate

## Owned paths

- `backend/tests/unit/test_phase5_gate.py`
- `docs/plans/professional-program-v2/task-contracts/P5-GATE.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- Phase 6 及以后。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- Gate 测试逐项覆盖 6 条并全部通过；全量 unit 无回归；ruff/mypy 通过。
