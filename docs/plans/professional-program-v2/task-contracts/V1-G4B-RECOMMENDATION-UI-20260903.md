# V1 G4B — Proactive Recommendation UI / Partial Apply

**Task:** `v1-g4b-recommendation-ui-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G4 Proactive Director Recommendation

## Outcome

- Shot Director 面板支持“主动分析当前镜头”（无需用户指令）；
- 展示结构化 recommendation current/suggested/reason/effect/risk/facts；
- 每项 typed operation 可勾选，实现 partial apply 到本地镜头草稿；
- 拒绝推荐清空预览；
- 不触发 /design、/execution-plan、/executions。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G4B-RECOMMENDATION-UI-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `frontend/src/features/director/api.ts`
- `frontend/src/features/director/suggestion-types.ts`
- `frontend/src/features/director/ShotDirectorSuggestionPanel.tsx`
- `frontend/tests/unit/ShotDirectorSuggestionPanel.test.tsx`

## Success Criteria

1. UI proactive recommendation passes；
2. partial apply only selected ops；
3. no runtime/execution calls；
4. frontend typecheck/lint/unit/build pass。

## Evidence

- vitest full：98 passed；
- ShotDirectorSuggestionPanel focused 4 passed；
- typecheck/lint/build passed；
- partial apply 不调用 /design 或 execution。
