# V1 G5A — Creation UX（Template/Free + Autonomy）

**Task:** `v1-g5a-creation-ux-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G5 Creation UX

## Outcome

- 项目创建 UI 支持：
  - 从模板开始（双人对白反转 / 单人情绪独白 / 自由短剧基础）；
  - 自由创建；
  - 导演参与度 AUTO/ASSIST/MANUAL；
- 创建后进入 `/script` Story 主链，不再默认 `/production`；
- 项目列表展示模板来源与 Autonomy。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G5A-CREATION-UX-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `frontend/src/lib/api.ts`
- `frontend/src/routes/index.tsx`
- `frontend/tests/unit/WorkstationShell.test.tsx`（如受影响）
- `frontend/tests/e2e/story-proposal.spec.ts` 或新增 creation spec

## Success Criteria

1. createProject 传递 start_type/template_key/director_autonomy；
2. UI 可选择模板与三档 Autonomy；
3. 创建后 navigate 到 script；
4. typecheck/lint/vitest/build pass。

## Evidence

- frontend full vitest 98 passed；
- typecheck/lint/build passed；
- API createProject 已支持 start_type/template_key/director_autonomy；
- 创建后导航到 `/script`。
