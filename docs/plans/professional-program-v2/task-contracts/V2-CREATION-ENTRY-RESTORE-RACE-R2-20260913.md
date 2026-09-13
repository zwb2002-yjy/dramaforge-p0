# Task: V2 — Creation Entry Restore Race R2

## Status

- **State:** COMPLETE
- **Task id:** `v2-creation-entry-restore-race-r2-20260913`
- **Goal:** Fix the user-reported double-click on the permanent `创作` entry that strands the Project root on `正在恢复上次创作位置…`.
- **Boundary:** Frontend L1 click semantics and Project-root last-view restoration only.

## Authority

- `navigation-ia/DramaForge_统一导航与项目大厅信息架构设计方案.md` §4–5, §7: permanent L1, Creative L2, existing-Project last-view restoration, and Scene fallback.
- `navigation-ia/DramaForge_统一导航与项目大厅执行方案.md` NAV-1 and NAV-5: one target-resolution rule, valid last view restore, invalid/missing fallback to `/scenes`.
- `V2-NAVIGATION-TRANSITION-UX-20260912.md`: internal navigation must preserve the live document and must not outrun the user's selected destination.
- `V2-CREATION-ENTRY-RESTORE-RACE-20260913.md`: preserved diagnosis and supersession reason; no implementation occurred under its malformed ledger ownership.

## Current Evidence / Drift

- Computer Use on the formal in-app browser reproduced tab 2 permanently at `/projects/42cddcd9-5451-4c95-b6b5-502e3dcbec43` with `正在恢复上次创作位置…`; a later accessibility refresh remained unchanged and browser logs contained no error.
- `ProjectLayout` sets `restoreRequested.current = true` before the first restore but does not reliably reset it while the parent route remains mounted. A second click can re-enter the Project root after the first restore, where the stale latch suppresses every later restore.
- The permanent `创作` L1 link remains navigable while already active. Clicking it from a Scene/Production/Edit workspace needlessly leaves the current page for the transient Project root; a double-click creates the observed re-entry race.

## Intended Logic / User-visible Outcome

1. While already inside the Creative module, clicking or double-clicking the active `创作` entry is idempotent and preserves the current workspace URL.
2. From Project Lobby or Settings, `创作` enters the remembered Project root, which resolves a valid `last_view` or falls back to `/scenes`.
3. Every Project-root entry can resolve again while `ProjectLayout` stays mounted; no one-shot latch can strand the transient restore screen.
4. The fixed L1/L2 structure, last-view persistence, Project facts, and business routes remain unchanged.

## Owned Paths

- `frontend/src/components/workstation/WorkstationShell.tsx`
- `frontend/src/routes/projects.$projectId.tsx`
- `frontend/tests/unit/WorkstationShell.test.tsx`
- `frontend/tests/unit/NavigationTransitions.test.tsx`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- this Task Contract

## Non-scope / Safety Boundary

- No API, workspace-state schema, route-tree, Project/Scene/Shot fact, database, runtime, Provider, paid operation, or persisted creative-data change.
- No new local navigation state machine and no change to the five Creative L2 destinations.
- No data deletion, project mutation, external transmission, or browser-tab cleanup.

## Verification

- Focused unit tests: active L1 click is prevented; Project root restores on initial entry and again after re-entry with the parent layout still mounted.
- Focused browser test: double-clicking active `创作` keeps the current Production URL and never exposes the restore message.
- Required regression: typecheck, lint, format check, deterministic full unit suite, production build, full Playwright suite, and `git diff --check`.
- Runtime: rebuild/restart the formal frontend and verify the exact reported interaction through the original in-app browser tab.

## Completion Conditions

- Intended logic above is covered by tests and visibly verified on the formal 8080 runtime.
- Changed paths remain inside the contract; source and closeout are committed; the local ledger records `COMPLETED` at the exact closeout commit.

## Completion Evidence

- Root cause: `ProjectLayout` used a parent-lifetime `restoreRequested` latch, so a second
  Project-root entry could be ignored after the first restore; the active `创作` L1 link
  also navigated away from the current Creative workspace unnecessarily.
- Implementation commit: `bfe53b2 fix(frontend): make creation restore idempotent`.
  Active L1 entries now prevent same-section navigation, and every Project-root entry can
  resolve server-backed `last_view` again without a one-shot latch.
- Focused verification: `WorkstationShell.test.tsx` and
  `NavigationTransitions.test.tsx` passed (23 tests); `navigation-ia.spec.ts` passed
  (5 tests).
- Full frontend verification passed: lint, format check, typecheck, build, deterministic
  Vitest (29 files / 165 tests), Playwright (23 tests), and `git diff --check`.
- Formal runtime frontend image:
  `sha256:c436bcd19477bea3b1102a9b6bf238c5f269d8143d4f93bb9e8b75a55985639b`;
  container health and `http://127.0.0.1:8080/healthz` passed.
- Computer Use on the original formal in-app Project tab double-clicked active `创作`
  while at `/projects/42cddcd9-5451-4c95-b6b5-502e3dcbec43/script`; the URL remained
  `/script` and `正在恢复上次创作位置…` never appeared.
- No API, database, Project/Scene/Shot fact, Provider, paid operation, external
  transmission, or browser-tab cleanup occurred.
