# V1 G7A — 统一主链 E2E（Story → Scene Workbench）

**Task:** `v1-g7a-mainchain-e2e-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G7 Unified Main Chain E2E

## Outcome

- 在同一 Project 上证明 Story Proposal Apply → Canonical Story → 同一个
  Scene/Shot Workbench；
- 复用既有 professional mock；不另建第二套 scene/execution mock。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G7A-MAINCHAIN-E2E-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `frontend/tests/e2e/v1-mainchain.spec.ts`

## Success Criteria

1. Playwright mainchain 通过；
2. 同一 projectId 从 /script 到 /scenes/:sceneId；
3. no direct second mock project state。

## Evidence

- `v1-mainchain.spec.ts` 1 passed；
- Story Apply 后同一 projectId 进入 Scene Workbench。
