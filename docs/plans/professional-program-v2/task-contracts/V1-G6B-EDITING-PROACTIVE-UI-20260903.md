# V1 G6B — OpenCut 主动剪辑建议 UI

**Task:** `v1-g6b-editing-proactive-ui-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G6 OpenCut Director Integration

## Outcome

- EditingWorkspace 增加“主动分析剪辑节奏”按钮，无需用户指令；
- 请求走 G6A 主动端点，复用现有 suggestionPreview / stale 逻辑。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G6B-EDITING-PROACTIVE-UI-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `frontend/src/features/editing/api.ts`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/tests/unit/EditingWorkspace.test.tsx`

## Success Criteria

1. UI typecheck/lint/build pass；
2. proactive 请求不带 user_instruction；
3. 不调用旧建议端点。

## Evidence

- EditingWorkspace focused 20 passed；
- full vitest 99 passed；
- typecheck/lint/build passed。
