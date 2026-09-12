# Task: V2 — Computer Use UX Sweep (raw enums, redundant copy, mobile table, L1 transition race)

## Status

- **State:** COMPLETE
- **Task id:** `v2-computer-use-ux-sweep-20260913`
- **Goal:** User-requested Computer Use deep review of the formal `127.0.0.1:8080` entry, repairing every
  defect found in product-visible wording, raw identifiers, redundant explanation, responsive reachability
  and the permanent-navigation transition.
- **Boundary:** Product-visible presentation plus one navigation-transition defect in the Project layout.
  No business behavior, contract, or data semantics changed.

## Environment / Method

- computer use is the DSH MCP bridge (`@deepseek-ai/dsh-mcp-client`) onto `@playwright/mcp@0.0.80`
  (Chrome channel, headless), mounted as `mcp-playwright` in `$DSH_HOME/profiles/web/cordis.patch.yml`
  through a loader `insert` row, which the running harness hot-loaded without a restart.
- The deployed stack was rebuilt from the working tree before the review: frontend `dramaforge-frontend:local`
  (`assets/index-1opFgczL.js` at review start), backend image with `reconcile.py sha256:388433a2…`,
  `source_commit` `3244d05985630aaab76d235305069134005af9cb`, and `.env` `DRAMAFORGE_SOURCE_COMMIT` aligned to
  that HEAD so the health endpoint no longer reported the previous release SHA.
- Pages walked at 1440×900 and 390×844 with DOM/accessibility assertions, console capture and layout metrics.

## Repairs

1. **Permanent L1 navigation was silently swallowed (real bug, reproducible in the browser, jsdom and
   Playwright).** Leaving a Project route for the Project Lobby or Settings replaced the user's own
   navigation: `ProjectLayout` rendered a `<Navigate>` restore that re-fired while the outgoing route was
   still mounted, and its effect ran while the router already reported the parent path. The restore is now an
   imperative `replace` guarded by the router's live pathname (`/projects/$projectId` only), so it can never
   outrun the entry the user clicked. Covered by `frontend/tests/unit/NavigationTransitions.test.tsx` and the
   existing `navigation-ia` E2E.
2. **Raw storage enums and internal names reached users.** Added product-facing label maps
   (`lib/shotLabels.ts`, `lib/assetLabels.ts`, `lib/creativeLabels.ts`, `lib/runLabels.ts`) and applied them:
   asset status filter (`active/draft/recycled` → 已启用/草稿/已回收), creative-capability selects and skill
   list, provenance summary, capability-probe results, experiment status, NodeRun/FinalFilm statuses, shot
   types (`medium-wide` → 中远景), asset kind/status, annotation severity/target, version status.
3. **Internal class names used as headings.** `Workflow Navigator` → 镜头工作流, `Creative Capabilities` kicker
   removed, `Canvas is source of truth` removed, `Canvas Revision` → 画布版本, `OpenCut` → 剪辑交接,
   `持久化 EditSession` → 剪辑会话, `Final Film Artifact` → 成片, `项目级 DirectorAutonomy` → 导演参与度,
   `Settings` eyebrow removed from every settings page, `Shot` table header → 镜头.
4. **Redundant explanation removed.** 制作 page heading/sub-heading/callout reduced to one statement; 场景 page
   eyebrow and product-tutorial sentence removed; page eyebrow paragraphs dropped from the script, asset,
   review and edit headers; slot identifiers (`planning.brief`, `visual.character`, `video.shot`) replaced by
   purpose labels; raw JSON `<pre>` blocks replaced by readable summaries with an explicit collapsed
   "view raw record" disclosure; turn id removed from generation evidence; project/scene/shot UUIDs removed
   from the edit timeline rows.
5. **Mobile reachability.** At 390×844 the 制作 page resolved its monitoring panel to 699 px inside a 302 px
   column and `.df-global-shell { overflow-x: hidden }` clipped the table's only per-row action. The mobile
   breakpoint now forces a shrinkable track, `min-width: 0`, cell padding and wrapped cells, so the panel is
   302 px, the action sits at 349 px inside the 390 px viewport, and the status grid no longer overflows.
6. **Silent disabled actions and false success.** Workspace `创建空间`/`删除` state their reason; asset `回收`
   asks for confirmation and reports the outcome, tags no longer claim "已保存" before the request succeeds,
   and the 制作 page renders failures as failures (`flash err`, `role=alert`) instead of green success.
7. **Dead affordances.** Scene `复制` → `复制场景` with a target-describing title; version status now uses
   Chinese labels; the provider service address honours a typed value on first creation.

## Non-scope held

No change to Project / Scene / Shot / Asset / Story facts, API contracts, generated clients, migrations,
Director runtime, Provider behavior, ProductionGraph, NodeRun, Artifact, Candidate/Formal/Export gates,
routing structure, navigation ownership, or the fixed L1/L2 information architecture. No real Provider call
and no paid operation.

## Verification

- `npx tsc --noEmit -p tsconfig.json` clean; `npx eslint src tests` clean; `npx prettier --check src tests` clean.
- Vitest: 29 files / 162 tests pass (baseline before this task was 28 files / 156 tests; the added file is the
  navigation-transition regression guard).
- Playwright: 21/21 pass.
- Formal 8080 entry rebuilt and re-walked through computer use: all ten walked routes land on their own path;
  L1 设置 and 项目 now navigate (`/projects/…/production → /settings/account → /`); no forbidden token
  (`Workflow Navigator`, `Creative Capabilities`, `OpenCut`, `Final Film Artifact`, `DirectorAutonomy`,
  `Shot Language`, `Quality Policy`, `user-explicit`, `auth_models`, `account_verified`, `planning.brief`,
  `visual.character`, `video.shot`, `clean baseline`, raw `wide/medium/closeup`) remains on the 制作 page;
  the 制作 monitor action is inside the 390 px viewport.

## Evidence

- Contract: this file.
- Navigation root cause: `history.push("/settings/account")` immediately followed by
  `history.replace("/projects/project-1/production")` from `ProjectLayout`'s restore effect.
- Commands: `npm run test -- --run`, `npm run test:e2e`, `docker compose -f docker-compose.yml
  -f docker-compose.build.yml build frontend`, `docker compose up -d --no-deps frontend`.
- Computer use artifacts: `.playwright-mcp/` page snapshots and console logs from this review.
