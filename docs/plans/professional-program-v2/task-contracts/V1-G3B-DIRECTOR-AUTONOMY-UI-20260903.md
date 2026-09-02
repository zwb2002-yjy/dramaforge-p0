# V1 G3B — 项目内 DirectorAutonomy 切换 UI

**Task:** `v1-g3b-director-autonomy-ui-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G3 DirectorAutonomy

## Outcome

- 新增 `CreativeAutonomySwitcher`，可在项目总览随时把 canonical
  ProjectCreativeProfile 在 AUTO / ASSIST / MANUAL 间切换；
- 使用 `PATCH /projects/{id}/creative-profile` 乐观锁，stale 不覆盖；
- 只改行为策略，不迁移 Project，不复制 Scene/Shot，也不触碰 Runtime。

## Owned Paths

- `frontend/src/features/project/CreativeAutonomySwitcher.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/routes/projects.$projectId.tsx`
- `frontend/tests/unit/CreativeAutonomySwitcher.test.tsx`
- `docs/plans/professional-program-v2/task-contracts/V1-G3B-DIRECTOR-AUTONOMY-UI-20260903.md`

## Verification

- focused Vitest：`CreativeAutonomySwitcher.test.tsx` 2 passed；
- frontend full Vitest 103 passed、lint/typecheck 通过。
