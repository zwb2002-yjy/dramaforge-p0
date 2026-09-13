# Task: V2 — Workspace Context Reopen Recovery

## Status

- **State:** COMPLETE
- **Task id:** `v2-workspace-context-reopen-recovery-20260913`
- **Goal:** Keep an authenticated Project readable after the last browser page is closed and
  reopened, instead of failing every Project API with `workspace context required`.
- **Boundary:** Browser-side workspace / recent-Project preference durability and safe
  Project-to-Workspace context recovery only.

## Authority

- `navigation-ia/DramaForge_统一导航与项目大厅执行方案.md` NAV-5 and NAV-6:
  Project entry has one predictable resolution path; refresh, browser back, direct entry,
  and the formal 8080 route must retain Project context.
- `navigation-ia/DramaForge_统一导航与项目大厅信息架构设计方案.md`: `last_view`
  remains server-backed and the Project selector changes context without copying facts.
- `backend/app/api/deps.py`: Project-scoped requests must continue to provide an owned,
  explicit `X-Workspace-Id`; this task must not weaken that tenant boundary.

## Current Evidence / Root Cause

- Formal Compose facts are healthy while the browser displays the failure: API,
  dispatcher, both production Workers, director Worker, frontend, PostgreSQL, Redis,
  MinIO, and LiteLLM remain `Up (healthy)`; the formal 8080 health endpoint returns 200.
- Computer Use on the reopened Project `/script` route visibly reports
  `无法读取项目事实：workspace context required`; the page also cannot read the Script.
- `dramaforge.selected-workspace-id` and `dramaforge.last-project-id` are stored only in
  `sessionStorage`. Closing the final page destroys that tab-scoped state even though the
  authenticated cookie and backend services remain alive.
- Direct Project routes mount Project queries before any Lobby or Settings page can select
  a Workspace, so a missing preference cannot currently self-recover.

## Intended Logic / User-visible Outcome

1. Workspace and recent-Project selections survive closing and reopening browser pages,
   while a login/owner transition can still clear the stored selection explicitly.
2. A direct authenticated Project URL first resolves an owned Workspace context. It tries
   the remembered Workspace, then the Owner's available Workspaces, and only mounts
   Project business queries after a matching Project is found.
3. Every Project API still carries an explicit owned Workspace header. No backend RLS,
   authorization, or Project ownership rule is relaxed.
4. A missing/deleted/inaccessible Project shows a human-readable recovery error with a
   route back to the Lobby; it is not mislabeled as a stopped service.
5. Server-backed Project `last_view` remains the only workspace-position fact.

## Owned Paths

- `frontend/src/lib/navigationPreferences.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/queryKeys.ts`
- `frontend/src/components/workstation/WorkstationShell.tsx`
- `frontend/src/routes/index.tsx`
- `frontend/tests/unit/navigationPreferences.test.ts`
- `frontend/tests/unit/WorkstationShell.test.tsx`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- this Task Contract

## Non-scope / Safety Boundary

- No backend route/dependency/RLS change; no auth cookie or credential persistence change.
- No Project/Scene/Shot/workspace-state mutation, data migration, Provider call, paid
  operation, external transmission, or browser-tab deletion.
- Do not interpret page polling as service lifetime; Compose remains process-owned and
  independent of the browser page.

## Verification

- Unit: durable preference read/write/clear and session restoration from durable storage.
- Unit: direct Project entry with no stored Workspace resolves the owning Workspace before
  rendering the Project route; a stale remembered Workspace falls back safely.
- E2E: clear the tab-scoped keys while keeping authentication, open an existing Project
  directly, and verify its facts render without `workspace context required`.
- Regression: focused tests, typecheck, lint, format check, deterministic full unit suite,
  build, full Playwright suite, `git diff --check`.
- Runtime: rebuild/restart only the formal frontend and verify the original in-app browser
  Project route recovers and remains readable across a fresh page.

## Completion Conditions

- The reported Project route visibly recovers without weakening Workspace isolation.
- Formal services remain healthy independently of the browser page.
- Changed paths remain inside the contract; source and closeout are committed; the local
  ledger records `COMPLETED` at the exact closeout commit.

## Completion Evidence

- Root cause confirmed: the formal Compose services never stopped. API, dispatcher,
  production Workers, director Worker, frontend, PostgreSQL, Redis, MinIO, and LiteLLM
  remained healthy. The selected Workspace and recent Project existed only in
  tab-lifetime `sessionStorage`, so closing the final browser page removed the header
  source while the authenticated cookie remained valid.
- Implementation commit: `b1c7401 fix(frontend): recover workspace context after reopen`.
  Navigation preferences now retain a per-tab value with a durable browser fallback;
  an explicit clear removes both tiers. A direct Project route validates the remembered
  Workspace, safely tries the Owner's other Workspaces when it is missing/stale, writes
  the resolved context before mounting child business queries, and keeps every API call
  explicitly Workspace-scoped.
- Failure UX is bounded: unresolved/deleted/inaccessible Projects show
  `无法恢复项目工作区` with a Lobby route. Backend `require_selected_workspace`, RLS,
  ownership, cookies, Project facts, and server-backed `last_view` were not changed.
- Verification passed: lint, format check, typecheck, production build, focused Vitest
  (navigation persistence / shell / transitions), deterministic full Vitest
  (30 files / 169 tests), focused navigation Playwright (6 tests), full Playwright
  (24 tests), and `git diff --check`. Existing router/mock warning noise remained
  non-failing and unchanged.
- Formal runtime frontend image:
  `sha256:6dcc2d52f4d3da07b3ce84b483eb5aace3989604acf299e91f101c6d35fac90f`;
  frontend container reached healthy and `http://127.0.0.1:8080/healthz` returned 200.
- Computer Use on the original failing in-app `/script` tab visibly transitioned from
  `正在恢复项目工作区…` to project `乌镇·枕水新生｜30秒字幕版 20260908`, its formal
  script, and ten Scene summaries, with no `workspace context required`. A separately
  opened fresh in-app page at the same direct URL also loaded the full Project facts.
- Computer Use verified Settings → `创作` restored the server-backed `/script` last view;
  browser warning/error logs were empty. The original Project tab was retained for the
  user and no user tab, Project data, Provider state, or external system was modified.
