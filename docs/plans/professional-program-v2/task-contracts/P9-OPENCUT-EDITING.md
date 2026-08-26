# Task: Phase 9 — OpenCut 剪辑（P9-00/01/02 + Gate）

## Status

- **State:** IN PROGRESS
- **Task id:** `p9-opencut-editing`
- **Program order:** Phase 8（COMPLETED）→ **Phase 9 OpenCut 剪辑（本任务）** → Phase 10
- **Task boundary:** P9-00 OpenCut Integration ADR（审计当前代码 + 选型）；P9-01 EditingAdapter（backend/app/editing/: create_session/load_timeline/save_timeline/export）；P9-02 Production → Edit Timeline（formal shot → edit session）；Phase 9 Gate（auto timeline → 手动剪辑 → 保存 → 重开 → export，production lineage 不变）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §80-86

## Owned paths

- `docs/plans/professional-program-v2/adrs/PHASE9-OPENCUT-INTEGRATION.md`
- `backend/app/editing/__init__.py`
- `backend/app/editing/adapter.py`
- `backend/app/editing/timeline_builder.py`
- `backend/app/editing/models.py`
- `backend/alembic/versions/20260827_0049_edit_sessions.py`
- `backend/tests/unit/test_editing_gate.py`
- `docs/plans/professional-program-v2/task-contracts/P9-OPENCUT-EDITING.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- ADR 审计当前 OpenCut + 选型。
- EditingAdapter create_session/load_timeline/save_timeline/export；持久化 edit_sessions。
- Production→Timeline：formal shot → clip timeline（保留 production lineage 引用）。
- Phase 9 Gate 测试（build → save → reopen → export；lineage 不变）。
- 全量 unit 无回归；ruff/mypy 通过。
