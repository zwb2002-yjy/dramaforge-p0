# Task: V2 — Canvas-first UI-1 and Production Delivery Foundation

## Status

- **State:** READY FOR ROOT REVIEW (not merged)
- **PR:** [#45](https://github.com/zwb2002-yjy/dramaforge-p0/pull/45) (`agent/v2-canvas-first-ui1-perf-foundation` → `dev`). Closed [#44](https://github.com/zwb2002-yjy/dramaforge-p0/pull/44) was the same work under the disallowed `feat/` head.
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

- Branch: `agent/v2-canvas-first-ui1-perf-foundation` from `dev` (`a2c3720`). CI `policy` requires `agent/*` HEAD for PRs into `dev`; the original `feat/…` name is retired.
- Layered commits (no `Co-Authored-By`):
  1. `64f8986` `docs(plan): add V2 Canvas-first UI-1 and perf foundation task contract`
  2. `6ca92c8` `perf(frontend): establish production delivery foundation`
  3. `0722ba2` `refactor(frontend): centralize query keys`
  4. `105b349` `feat(workbench): implement canvas-first UI-1`
  5. `dc32856` `test(frontend): cover canvas-first and production-entry regressions`
  6. `648cb7f` `docs(plan): record V2 UI-1 8080 acceptance evidence`
  7. review follow-up (this commit): `agent/*` rename, Prettier on the 6 failing files, compression lockfile `resolved` URLs aligned to `registry.npmmirror.com`, Context Dock tools, technical metadata sunk into Details.
- UI-1 composition: `ContextDock` tools are Character / Camera / Motion / Look / Generate / Director / Takes / Details. Character opens identity references + description; Camera / Motion / Look focus the existing Shot design fields; Director is the suggestion surface; Generate is production actions only. `DirectorSidebar` filename kept as a floating 320–360px Context Sheet. Candidate Tray collapsed + compact ShotStrip + on-demand `ShotDetailsPanel`. Pure UI state only (`activeTool`, `trayExpanded`, `stripExpanded`, `detailsOpen`). Scene layout is a single column; sheets float over the Canvas.
- Generate no longer mounts `ShotProductionTrace`, `v{shot.version}`, or `NodeRun：status`. Those facts live in the Details sheet. Production-facing status is `已排队` / `处理中`.
- Query keys: factory consumed across frontend; tuple shapes unchanged. `generated.ts` untouched.
- Route splitting: code-based `lazyRouteComponent` wrappers in `frontend/src/routes/pages.ts`. No file-based router rewrite.
- Gzip: `vite-plugin-compression2` `algorithms: ["gzip"]` only; `nginx.conf` `gzip_static on;`.

### Bundle (Vite production, this HEAD)

| chunk | raw | gzip |
| --- | ---: | ---: |
| `index-Dxgs7vNr.js` (entry) | 52.73 KB | 16.02 KB |
| `vendor-react-CZODMRGO.js` | 142.94 KB | 45.78 KB |
| `vendor-tanstack-DB12fQOR.js` | 129.81 KB | 40.97 KB |
| `vendor-lucide-DPWvzUW5.js` | 7.32 KB | 1.99 KB |
| `SceneWorkspace-Dv84Hhyc.js` | 41.41 KB | 11.44 KB |
| `production-page-Dzyw3A7Y.js` | 43.29 KB | 12.72 KB |
| `EditingWorkspace-Ct1jm-dx.js` | 26.95 KB | 8.07 KB |
| `index-Dg0OZ6Vo.css` | 115.48 KB | 17.20 KB |

Before Commit 1 the SPA entry was a single ~448 KB JS file. Entry is now 52.73 KB (gzip 16.02 KB); vendor families and Scene/production/edit routes are separate chunks with `.gz` siblings.

## Verification

- `frontend/`: `npm run lint` PASS; `npm run typecheck` PASS; `npm run test` PASS (114); `npm run format:check` PASS; `npm run test:e2e` PASS (15); `git diff --check` PASS. Review follow-up re-ran lint / typecheck / 114 unit / 15 E2E / format:check.
- `npm run api:check` not run on the Windows host: `backend/.venv` is a Linux uv venv (`bin/python`) and host Python has no FastAPI. `frontend/src/shared/api/generated.ts` was not modified in this PR; skip is not a frontend regression.
- Frontend image rebuilt as `dramaforge-frontend:local` and `dramaforge-frontend-1` recreated. Acceptance against `http://127.0.0.1:8080`:
  - `/gateway-health` → 200 `ok`
  - `/health` → 200 JSON
  - `/` → 200 HTML, `Content-Encoding: gzip`
  - `/assets/index-Dxgs7vNr.js` and `/assets/vendor-react-CZODMRGO.js` → 200, `Content-Encoding: gzip`
  - `/assets/SceneWorkspace-Dv84Hhyc.js` → 200, `Content-Encoding: gzip` (11415 bytes)
  - SPA fallback: `/projects/.../scenes/...` → 200 `index.html`
  - `/api/v1/auth/login` + `/api/v1/auth/me` + `/api/v1/workspaces` same-origin proxy works
  - image contains `--with-http_gzip_static_module`; `gzip_static on;` in `/etc/nginx/conf.d/default.conf`; 16 `.gz` siblings under `/usr/share/nginx/html/assets`
- Live 8080 Scene (`/projects/da618e29-e46d-4b74-824a-2cca1428b8f2/scenes/fb799a90-15d7-4335-b6aa-18d5a57a3914`): Context Dock present; no `director-sidebar`; ShotStrip compact (`data-expanded=false`); Canvas ~1122px in a 1-column `.qc-scene-layout`; no horizontal overflow; hard refresh keeps the same shell. Workspace GET currently 500 `ProgrammingError` (`column node_runs.production_batch_id does not exist`) — pre-existing API/schema drift, not this frontend PR. Canvas-first chrome still renders and reports the server error in `.flash.err`.
- Unit/E2E cover: default no permanent right panel; dock-first Context Sheet; collapsed tray; Candidate Preview zero POST; Formal confirm + refetch; 1440×900 and 910×838 no overflow.
