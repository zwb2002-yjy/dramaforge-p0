# V1 G1B — Story Authoring Proposal UI

**Task:** `v1-g1b-story-proposal-ui-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G1 Story Authoring Proposal Chain
**Depends on:** V1-G1A backend（dev `5a544e4`）

## Outcome

Script 工作区提供 Story proposal-first 体验：

- 输入 brief + markdown draft 创建 proposal；
- 展示 typed diff（create/update/delete）与 key；
- 用户 whole / partial apply；
- 查看 rejected / applied 后刷新 Canonical Story；
- 不显示旧“导入即写 Canonical”的唯一入口（保留既有 GET 显示，禁止直接 import UI 作为新故事入口）。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G1B-STORY-PROPOSAL-UI-20260903.md`
- `frontend/src/features/script/api.ts`
- `frontend/src/features/script/ScriptWorkspace.tsx`
- `frontend/tests/unit/ScriptWorkspace.test.tsx`
- `frontend/tests/e2e/story-proposal.spec.ts`

## Explicitly Out of Scope

- AI 文本模型 transport；
- G2/G3/G4；
- 删改后端 Story proposal API。

## Success Criteria

1. UI 可创建 proposal 并显示 operations；
2. Whole apply 一键采用并刷新 Script/Episode/Scene；
3. Partial apply 只发送勾选项；
4. unit 覆盖 create/preview/apply/reject；
5. Playwright 覆盖创建 → 部分采用 → canonical 刷新；
6. frontend lint/typecheck/unit/build 通过。

## Evidence

- commit SHA：提交后回填；
- vitest focused：`ScriptWorkspace.test.tsx` 4 passed；
- Playwright focused：`story-proposal.spec.ts` 1 passed；
- frontend typecheck/lint/build：通过；full vitest 97 passed。
