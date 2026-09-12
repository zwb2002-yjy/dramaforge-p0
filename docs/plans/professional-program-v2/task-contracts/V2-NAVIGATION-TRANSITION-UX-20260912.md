# Task: V2 — Navigation Transition UX

## Status

- **State:** IN PROGRESS
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

- Record exact commits, commands, runtime image, and Computer Use observations after implementation.
