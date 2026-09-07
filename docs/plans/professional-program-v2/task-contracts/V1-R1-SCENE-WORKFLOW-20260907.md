# V1 R1 — Scene waiting, draft safety, and stage actions

**Task:** `v1-r1-scene-workflow-20260907`\
**Parent:** G5 / UI-1 / G7A\
**Status:** COMPLETE\
**Baseline:** `dev@67bbde25f6e9739ff2259f678394c63b2c37284a`

## Problem

The Scene aggregate is invalidated once after submission but does not continue
polling while its effective NodeRuns are active. Closing the Context Sheet
unmounts the design editor and drops its local draft, while changing Shot clears
the dirty flag and suggestion draft without an explicit save/discard choice.
Production buttons do not consume the authoritative trace, so a running stage
can be submitted again and the UI only distinguishes the HTTP mutation itself.

Editing recovery was observed working against the existing runtime in R0. It is
not modified unless a focused R1 test reproduces an additional defect.

## Outcome

- Poll the canonical Scene workspace every four seconds only while the newest
  effective run for any Shot/node is queued, running, or cancel-requested.
- Stop polling at terminal state and show connection interruption without
  changing the server run to failed.
- Preserve the selected Shot draft when the Context Sheet closes.
- Block Shot changes and route departures while dirty until the user returns to
  save or explicitly discards; a discarded Shot draft cannot appear on another
  Shot.
- Feed the selected Shot trace to production actions, distinguish submission
  from server execution, and disable only the currently active stage.

## Owned paths

- `frontend/src/features/scenes/SceneWorkspace.tsx`
- `frontend/src/features/production/sceneRunState.ts`
- `frontend/src/features/scenes/UnsavedChangesDialog.tsx`
- `frontend/src/features/director/DirectorSidebar.tsx`
- `frontend/src/features/shots/ShotDesignPanel.tsx`
- `frontend/src/features/shots/ShotProductionActions.tsx`
- `frontend/src/routes/projects.$projectId.scenes.$sceneId.tsx`
- `frontend/src/components/workstation/project-shell.css`
- focused frontend unit/E2E tests for these behaviors
- this contract and Goal status

## Invariants

- React Query remains the only server-state source; no second production store
  or event framework is introduced.
- Candidate preview remains zero-write and Formal selection remains explicit.
- Dirty client drafts never authorize production or overwrite a different Shot.
- Polling performs reads only and terminates on effective terminal state.
- Existing Project/Shot/version/reference/model identity checks are unchanged.

## Acceptance

1. A queued → running → completed fixture updates to the new candidate without
   user refresh, then stops polling.
2. Closing and reopening the Context Sheet retains draft text. Changing Shot
   opens a save/discard guard; cancel keeps Shot A and its draft, discard changes
   to B and B shows only B values.
3. Save failure leaves the controlled draft and production dirty gate intact.
4. A newer successful attempt prevents an older failed/active row from becoming
   the effective UI state.
5. Active keyframe/video trace disables the matching action and exposes queued,
   running, and cancel-requested wording distinct from request submission.
6. Router navigation and browser unload are blocked while dirty, with an explicit
   return-to-save or discard-and-leave choice.

## Tests

- Focused Vitest: SceneWorkspace, ShotProductionActions, route blocker helper if
  extracted, plus existing Editing recovery regression.
- Frontend format, lint, native TypeScript 7 typecheck, unit suite, API check and
  build.
- E2E Scene workflow regression using controlled backend fixtures; no Provider
  call or live creative write.

## Result

- Scene aggregate polling now follows only the newest effective NodeRun for each
  Shot/node, runs every four seconds while that state is active, and stops on a
  terminal state. A read failure keeps the last server state visible and labels
  it pending synchronization instead of manufacturing a failure.
- Scene-owned design drafts survive Context Sheet unmounts. Dirty Shot changes
  and route departures now require an explicit return-to-save or discard choice;
  failed saves preserve the draft and keep production gated.
- Production actions consume the server trace, distinguish request submission
  from queued/running/cancel-requested execution, and prevent duplicate submits
  only for the matching active stage.
- Isolated backend quality evidence: Ruff PASS, MyPy `236` files PASS, backend
  unit suite `900` PASS, PostgreSQL migrations/check PASS, PostgreSQL integration
  suite `20` PASS, and current OpenAPI export produced.
- Isolated frontend quality evidence against that OpenAPI export: generated API
  check, Prettier, ESLint, native TypeScript 7 typecheck and production build all
  PASS; Vitest `28` files / `140` tests PASS; Playwright `18` tests PASS.
- The isolated verified source and the R1 runtime/test files in the integration
  worktree have identical SHA-256 values. `git diff --check` PASS. No Provider
  request, paid generation, runtime deployment, or user-owned file mutation was
  performed.

## Next

R2 owns the real text-model Director transport and durable invocation evidence.
