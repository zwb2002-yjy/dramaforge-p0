# Task: V2 — Canvas-first UI-1 and Production Delivery Foundation

## Status

- **State:** IN PROGRESS
- **Task id:** `v2-canvas-first-ui-1-and-perf-foundation`
- **Program order:** P10 UI consolidation and Visual 2.1 refinement → **V2 Canvas-first UI-1 + frontend engineering governance**
- **Boundary:** One frontend-convergence PR: Canvas-first V2 first productization round, frontend engineering debt governance (route splitting / vendor chunks / gzip / query key factory), loading/error/empty state completion for touched views, and full verification against the formal 8080 Nginx entry. Does not touch creative/production facts or API semantics.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`P10-UI-VISUAL-REFINEMENT.md`](P10-UI-VISUAL-REFINEMENT.md) — Visual 2.1 completion state and forbidden-change baseline this task builds on
- External design brief (Owner-provided): `DramaForge Canvas-first 创作工作台 V2.md` — product principles (Canvas is the Product, Context Tool Dock, progressive depth, technical details sunk into Details) and phases UI-1…UI-8
- External governance conclusion (Owner-provided): `DramaForge_前端大PR治理_AgentRuntime兼容性_8080正式入口.md` — approved single-PR / layered-commit shape, Agent Runtime compatibility prohibitions, and the 8080 formal-entry acceptance gates

## Approved shape (Owner 2026-09-03)

- One medium-large PR from `dev`, layer-committed, merged only after root review:
  1. `perf(frontend): establish production delivery foundation` — route splitting, vendor chunks, gzip precompression, 8080 delivery validation.
  2. `refactor(frontend): centralize query keys` — query key factory + invalidate organization; cache semantics unchanged.
  3. `feat(workbench): implement canvas-first UI-1` — ContextDock, Context Sheet, conditional Candidate Tray, compact ShotStrip, Details sink, Scene loading/error/empty states.
  4. `test(frontend): cover canvas-first and production-entry regressions` — unit, E2E, responsive, 8080 formal-entry smoke.
- Big PR is acceptable only because every commit serves the same "frontend convergence" goal.

## V2 UI-1 goals

- Default Scene view: Canvas is the dominant visual region; no permanent right operation panel, no permanent Candidate Tray, no permanent technical status.
- New Context Dock under the Canvas (Character / Camera / Motion / Look / Generate / Director / Takes / Details); at most one tool surface open; surfaces float over the Canvas (320–360px Context Sheet) and closing restores full Canvas width.
- Candidate Tray collapses to a one-line "Takes · N" and expands only on demand (after Generate, in review, or by explicit open).
- ShotStrip gains compact (default) / expanded states.
- Execution metadata (Provider / NodeRun / Artifact / lineage / version / trace) moves into an on-demand Details surface.
- Pure UI state only: `activeTool`, `candidateTrayExpanded`, `shotStripExpanded`, `detailsOpen`. No `workspaceContext` FSM, no second store of server facts.
- Preserve: preview precedence (explicit Candidate Preview > Formal Video > Formal Keyframe), Candidate click = local preview only (zero writes), Use-as-Formal → refetch → Formal restored, stale fail-closed, Shot-version-from-server truth.
- Preserve Visual 2.1 token language (`--df-*`, obsidian/brass); no purple, gradients, glass, or glow.

## Performance governance

- TanStack Router code-based routing only: route splitting via official `Route.lazy()` / `createLazyRoute` or `lazyRouteComponent`; no file-based router, no `autoCodeSplitting`, no URL/params/route-identity change, no route-tree rewrite.
- Vite `manualChunks` vendor split (react, @tanstack, zustand, lucide).
- `vite-plugin-compression2` with explicit `algorithms: ["gzip"]` only (formal Nginx consumes `.gz` this round).
- `nginx.conf`: `gzip_static on;` — and verify the frontend image's Nginx includes `ngx_http_gzip_static_module` (`nginx -V`); if absent, fall back to dynamic `gzip on` without changing the deployment architecture.

## Allowed paths

- `frontend/vite.config.ts`, `frontend/package.json`
- `frontend/nginx.conf`, `frontend/Dockerfile`
- `frontend/src/router.tsx`, `frontend/src/routeTree.gen.ts` consumers, `frontend/src/routes/*`
- `frontend/src/lib/queryKeys.ts`, `frontend/src/lib/api.ts`, `frontend/src/features/{scenes,shots,director}/*`
- `frontend/src/components/workstation/*`, `frontend/src/stores/uiStore.ts`
- `frontend/src/styles/index.css`
- `frontend/tests/**`
- this Task Contract

## Forbidden changes

- Do not change Scene/Shot/Asset/Runtime facts, API/schema, ORM, DB/migration, Provider, Worker, Graph, NodeRun semantics, ExecutionModelResolver, OpenCut, generation semantics, or URL/route semantics.
- Do not introduce a second token system, a browser-side Agent/second-truth store, a workspace state machine, or pre-built Agent Runtime SDKs (Gateway/CommandBus/ServiceContainer).
- Do not make the UI a business state machine over NodeRun status; production-facing language first, technical ids in Details.
- Do not replace DOM/layout verification with screenshots.

## Verification gate

- `npm run lint`, `npm run typecheck`, `npm run test`, `npm run api:check`, `npm run build`, `npm run test:e2e`, and `git diff --check` pass in `frontend/`.
- Frontend image rebuilt and container recreated; acceptance runs against `http://localhost:8080`:
  - `/gateway-health` → 200, `/health` → 200, `/` → 200
  - real Scene route direct visit + refresh via SPA fallback
  - `/api/*` same-origin proxy works
  - new JS/CSS chunks load; `.gz` assets copied into the image and served (gzip verified in-container or via `Content-Encoding: gzip`)
  - page is the new Canvas-first UI (not a stale 5173-only success)
- Scene/Shot behavior: no permanent right panel by default; Context Sheet opens/closes without mutating facts; Candidate Preview zero writes; Formal confirmation refetches to Formal; Shot switching leaks no draft/preview; no horizontal overflow at 1440×900 and 910×838.
- Bundle before/after record: main JS, route chunks, vendor chunks, gzip size, total JS.

## Implementation evidence

_(filled on completion)_

## Verification

_(filled on completion)_
