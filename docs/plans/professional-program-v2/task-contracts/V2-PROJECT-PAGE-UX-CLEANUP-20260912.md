# Task: V2 — Project Page UX Cleanup

## Status

- **State:** COMPLETE
- **Task id:** `v2-project-page-ux-cleanup-20260912`
- **Goal:** User-requested Computer Use review and cleanup of redundant Project-page UI.
- **Boundary:** Frontend-only presentation and interaction changes for the Project Lobby and shared Project workspace shell.

## Current Evidence / Drift

- Computer Use against the current source-built `http://127.0.0.1:8080` entry shows an empty “继续创作” card even when the workspace already contains many Projects and no last Project has been remembered in the browser session.
- The Lobby renders all 65 Projects at once, creating an unnecessarily long mobile page.
- `PROJECTS`, explanatory architecture copy, a healthy-service badge, and a “项目卡片只呈现…” note repeat information already conveyed by the shell and page structure.
- Every non-Scene Project route appends a generic “项目证据 / 同一事实源 / 事实边界” inspector. On mobile it appears after the actual workspace, while on desktop it consumes a permanent right column. The Project header also exposes the internal “已连接项目事实” label.

## Outcome

- The Lobby leads with its title and the New Project action, without healthy-state or internal design explanation clutter.
- “继续创作” appears only when an actual remembered Project can be resumed.
- The Project list initially renders a useful bounded set and exposes an explicit progressive “show more” action without hiding search results or deleting Project data.
- Shared Project pages no longer render the generic evidence inspector or internal fact-connection label; domain-specific production/review evidence remains unchanged.

## Owned Paths

- `frontend/src/routes/index.tsx`
- `frontend/src/routes/projects.$projectId.tsx`
- `frontend/src/components/workstation/ProjectWorkspaceShell.tsx`
- `frontend/src/components/workstation/navigation-shell.css`
- `frontend/tests/unit/WorkstationShell.test.tsx`
- `frontend/tests/e2e/professional-manual.spec.ts`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- this Task Contract

## Non-scope and Boundaries

- Do not delete or mutate Projects, Workspaces, users, or runtime data.
- Do not change API, database, model/provider, production, editing, Candidate/Formal, or Director semantics.
- Do not remove domain-specific evidence required by Production, Review, Editing, or delivery workflows.
- Do not change Project entry/last-view behavior or the fixed `项目 / 创作 / 设置` navigation hierarchy.

## Verification

- Focused Vitest coverage proves empty continuation UI is absent, the list is initially bounded and can expand, and the generic Project evidence inspector is absent.
- Focused Playwright coverage proves desktop/mobile Project routes remain one-column without the generic inspector and have no page-level horizontal overflow.
- Frontend lint, typecheck, unit tests, build, focused E2E, and `git diff --check` pass.
- Rebuild the formal 8080 frontend and re-run Computer Use to visibly verify the cleaned Lobby and Project page.

## Completion Evidence

- Implementation commit: `8be4962` (`fix(frontend): streamline project pages`).
- `npm run lint`: PASS.
- `npm run typecheck`: PASS.
- `npm run format:check`: PASS.
- `npm run build`: PASS (1,791 modules transformed; production chunks and gzip assets emitted).
- `npm run test -- --reporter=dot`: PASS — 28 files / 156 tests.
- `npm run test -- --reporter=dot --maxWorkers=1`: PASS — deterministic full-suite confirmation, 28 files / 156 tests.
- `npm run test:e2e`: PASS — 21 Chromium tests, including the new Lobby-clutter and Project-inspector regressions.
- `git diff --check`: PASS.
- Formal entry: `/gateway-health` and `/health` both returned HTTP 200; API reported database and LiteLLM up.
- Rebuilt frontend image: `dramaforge-frontend@sha256:b3c2cb6dec8c755add41b8bc2727a9e8ca3a31df77f0d72aab8b66ad3fbd592e`; recreated `dramaforge-frontend-1` was healthy on `127.0.0.1:8080`.
- Computer Use on the rebuilt formal entry verified:
  - the Edit workspace no longer renders “项目证据”, “同一事实源”, “事实边界”, or “已连接项目事实”;
  - the Lobby no longer renders the `PROJECTS` eyebrow, healthy-service badge, architecture explanation, card-explanation note, or empty continuation placeholder;
  - a real 68-Project workspace initially renders 12 cards, and activating “显示更多项目（剩余 56 个）” expands it to 24 while preserving every Project record.
- No Project, Workspace, user, Provider, runtime, or artifact data was deleted or mutated by this Task.
