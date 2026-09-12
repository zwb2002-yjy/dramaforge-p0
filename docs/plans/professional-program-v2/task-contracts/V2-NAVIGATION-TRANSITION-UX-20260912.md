# Task: V2 — Navigation Transition UX

## Status

- **State:** COMPLETE
- **Task id:** `v2-navigation-transition-ux-20260912`
- **Goal:** User-requested follow-up Computer Use review and repair of page navigation and switching behavior.
- **Boundary:** Frontend global navigation transitions and mobile L2 drawer behavior only.

## Current Evidence / Drift

- Computer Use on the source-built formal `127.0.0.1:8080` entry proves that, at the mobile viewport, selecting `剧本` from an open Creative L2 drawer navigates successfully but leaves the drawer expanded over the new page.
- The same behavior is reproduced when switching from `当前项目设置` to `账号与实例` inside Settings.
- The global brand, current-Project Settings entry, current Project Settings L2 entry, and New Project action use raw internal `<a>` navigation, causing unnecessary full-document transitions instead of using the existing TanStack Router.
- The mobile L2 drawer can only be closed with the small rail toggle; it has no outside-click target or Escape-key dismissal.

## Outcome

- Successful route, search, or hash transitions automatically close the mobile L2 drawer so the destination is immediately visible.
- The mobile drawer can also be dismissed by clicking its backdrop or pressing Escape.
- Internal product destinations use TanStack Router links and retain the live application document during page switching.
- Global L1 order, Creative/Settings L2 ownership, active states, Project last-view restoration, and all business behavior remain unchanged.

## Owned Paths

- `frontend/src/components/workstation/WorkstationShell.tsx`
- `frontend/src/components/workstation/navigation-shell.css`
- `frontend/tests/unit/WorkstationShell.test.tsx`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- this Task Contract

## Non-scope and Boundaries

- No Project, Workspace, auth, API, database, Director, Provider, Production, Editing, Candidate, Formal, or artifact changes.
- No change to the fixed `项目 / 创作 / 设置` L1 or `剧本 / 资产 / 场景 / 制作 / 剪辑` Creative L2.
- Do not alter the existing new/existing/stale last-view entry rules.
- Do not create a navigation-derived business state machine.

## Verification

- Unit coverage proves mobile route transitions, backdrop click, and Escape dismiss the drawer while desktop route switching preserves its expected layout.
- Playwright proves Creative and Settings L2 selections close the mobile drawer, internal Settings navigation does not reload the document, and 390×844 has no page-level horizontal overflow.
- Frontend lint, typecheck, format, full unit, build, full E2E, and `git diff --check` pass.
- Rebuild the formal 8080 frontend and verify the repaired transition through Computer Use.

## Completion Evidence

- Contract commit: `3244d05` (`docs(task): bound navigation transition UX`).
- Navigation implementation landed in `b360353` (`fix(frontend): remove internal identifiers from the UI and unblock L1 navigation`); the Computer Use follow-up corrected the mobile backdrop hit area in `9db3afb` (`fix(frontend): align mobile navigation backdrop`).
- Focused verification:
  - `npx vitest run tests/unit/WorkstationShell.test.tsx tests/unit/NavigationTransitions.test.tsx --reporter=dot` — 2 files / 21 tests passed.
  - `npx playwright test tests/e2e/navigation-ia.spec.ts --reporter=line` — 3/3 passed, including mobile route-close, Escape, backdrop geometry/click, Settings stability, and no horizontal overflow.
- Frontend gates:
  - `npm run lint`, `npm run typecheck`, `npm run format:check`, and `npm run build` passed.
  - `npm run test -- --reporter=dot --maxWorkers=1` — 29 files / 162 tests passed. The unconstrained parallel run hit existing 1-second mount timeouts in navigation tests under local CPU contention; deterministic single-worker execution passed the complete suite without assertion failures.
  - `npm run test:e2e` / `npx playwright test --reporter=dot` started all 21 tests and `.last-run.json` recorded `status: passed` with no failed tests.
  - `git diff --check` passed.
- Formal runtime:
  - Source commit: `9db3afb`.
  - `docker compose -f docker-compose.yml -f docker-compose.build.yml build frontend` and `up -d --no-deps frontend` completed.
  - `dramaforge-frontend:local` image id/digest: `sha256:cd647c3c4cfa55a9d9643cf846cac974a97f61cecf33096e879d02833f7745a3`.
  - `http://127.0.0.1:8080/healthz` and the requested Project edit route both returned HTTP 200; the frontend container reported healthy.
- Computer Use / browser observations at 390×844 on the formal 8080 runtime:
  - Creative L2 opened at x=56..252 while the outside-close backdrop occupied only x=252..390; clicking the labelled backdrop closed L2 immediately.
  - Selecting a different Creative page updated the route and exposed the destination with L2 closed; Escape also closed the drawer.
  - Permanent Settings navigated to `/settings/account`; selecting Current Project Settings navigated to `/settings/projects/42cddcd9-5451-4c95-b6b5-502e3dcbec43` and automatically closed L2.
