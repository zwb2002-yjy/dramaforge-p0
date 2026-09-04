# V1 G6D — Editing Suggestion whole/partial/reject 应用到草稿

**Task:** `v1-g6d-editing-suggestion-apply-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G6 OpenCut Director Integration

## Outcome

- EditingWorkspace 为 pending suggestion 增加：
  - 全部采用到草稿；
  - 按 typed operation 勾选的部分采用；
  - 拒绝清空预览；
- typed reorder/duration 操作只写入本地 timeline 草稿，必须显式保存才会成为
  新 EditSession version；拒绝和建议状态不影响 formal production lineage。

## Owned Paths

- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/tests/unit/EditingWorkspace.test.tsx`
- `docs/plans/professional-program-v2/task-contracts/V1-G6D-EDITING-SUGGESTION-APPLY-20260903.md`

## Verification

- EditingWorkspace focused 25 passed（全选、部分选、拒绝、save PATCH body）；
- frontend lint/typecheck 通过。
