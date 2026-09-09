# Task: V2 — Unified Navigation and Project Lobby Information Architecture

## Status

- **State:** IMPLEMENTED / READY FOR OWNER REVIEW（worktree；NAV-7 commit-bound Gate pending）
- **Task id:** `v2-unified-navigation-and-project-lobby-20260904`
- **Authority:** Owner amendment, 2026-09-04
- **Program order:** V1 unified creative mainchain + V2 Canvas-first UI-1 → **Unified navigation and project lobby IA**
- **Boundary:** Frontend information architecture, global/project/settings navigation ownership, Project Lobby responsibility, product-visible terminology, project-entry behavior, and focused verification. No backend or runtime semantic changes.

## Read first

1. [`../README.md`](../README.md)
2. [`../v1-goal/DramaForge_V1_最终创作与导演架构设计方案.md`](../v1-goal/DramaForge_V1_最终创作与导演架构设计方案.md)
3. [`../navigation-ia/DramaForge_统一导航与项目大厅信息架构设计方案.md`](../navigation-ia/DramaForge_统一导航与项目大厅信息架构设计方案.md)
4. [`../navigation-ia/DramaForge_统一导航与项目大厅执行方案.md`](../navigation-ia/DramaForge_统一导航与项目大厅执行方案.md)
5. [`V2-CANVAS-FIRST-UI-1-AND-PERF-FOUNDATION-20260903.md`](V2-CANVAS-FIRST-UI-1-AND-PERF-FOUNDATION-20260903.md)
6. Current frontend code, route tree, DOM tests, E2E, and formal 8080 runtime evidence

## Owner decisions frozen by this Task

- DramaForge has one product, one creative mainchain, and one workbench.
- Quick / Professional are not product modes, navigation dimensions, workbench choices, or runtime paths.
- Template / Free Start only select the project starting point.
- AUTO / ASSIST / MANUAL only select Director participation level.
- Global L1 is permanently `项目 / 创作 / 设置`.
- Creative L2 is `剧本 / 资产 / 场景 / 制作 / 剪辑`.
- Review belongs to Production / Shot workflow and is not a peer creative workspace.
- Project Lobby is for finding, continuing, and creating Projects; settings and workspace administration are separate.
- New Project enters Script; existing Project restores a valid last view; missing/invalid last view falls back to the Scene storyboard wall.

## Current evidence / drift

- `ProjectLobbyShell` and `ProjectWorkspaceShell` separately own two different sidebar structures.
- `开始创作` is incorrectly represented as navigation.
- Provider connection, workspace CRUD, and Project listing render in the same Dashboard.
- Project model settings render through anchors inside Project overview rather than an independent settings space.
- Existing Project cards navigate directly to `/production`, while newly created Projects navigate to `/script` and the Project root has separate last-view restore behavior.
- Product-visible `专业生产` / `专业模式` terminology preserves a retired dual-product mental model.
- Review is presented as a peer of Script / Assets / Scenes / Production / Edit.

## Approved execution sequence

1. `NAV-0` Current matrix and terminology freeze.
2. `NAV-1` Single global Shell and permanent L1.
3. `NAV-2` Project L2 and Project Lobby recomposition.
4. `NAV-3` Independent Settings space and responsibility migration.
5. `NAV-4` Unified creative L2, Review ownership, retired term cleanup.
6. `NAV-5` Project entry / restore / fallback convergence.
7. `NAV-6` Responsive, accessibility, and 8080 E2E.
8. `NAV-7` Current-HEAD gate and documentation closeout.

Each implementation unit must either receive a child bounded Task Contract or be delivered as a separately reviewable commit with its own Current Evidence, focused tests, and gate result.

## Expected owned paths

- `frontend/src/components/workstation/*`
- `frontend/src/components/shell/*`
- `frontend/src/routes/*`
- `frontend/src/router.tsx`
- `frontend/src/routeTree.gen.ts` consumers
- `frontend/src/stores/uiStore.ts`
- `frontend/src/styles/index.css`
- `frontend/src/components/workstation/*.css`
- focused `frontend/tests/unit/*`
- focused `frontend/tests/e2e/*`
- this Task Contract and the two registered navigation-IA documents

Exact paths must be narrowed per implementation unit before code changes.

## Forbidden changes

- No Project / Scene / Shot / Asset / Candidate / Formal fact changes.
- No API, ORM, database, migration, RLS, or auth semantic changes.
- No Production Graph, NodeRun, ProviderOperation, Artifact, Worker, Runtime, model resolution, generation, or repair semantic changes.
- No OpenCut, EditSession, Timeline, export, or Final Film semantic changes.
- No Quick / Professional compatibility UI or second workbench.
- No navigation-derived browser business state machine.
- No redesign of Scene Canvas, Context Dock, Candidate Tray, Shot Strip, or Details beyond layout compatibility required by the new Shell.
- No broad token-system or visual-system rewrite.

The earlier V2 UI-1 prohibition on route-semantic changes remains in force except for the narrowly authorized settings routes and Project-entry/navigation behavior defined by this Owner amendment.

## Verification gate

- L1 contains exactly `项目 / 创作 / 设置` and retains identical structure/order across Lobby, Project, and Settings routes.
- Every L2 item has one L1 parent and both levels expose correct active state.
- Project Lobby contains no Provider connection, workspace CRUD, Model Profile, or current-Project settings form.
- `新建项目` is an action, not a navigation item.
- Creative L2 contains `剧本 / 资产 / 场景 / 制作 / 剪辑`; Review remains reachable under the correct Production / Shot context.
- Product-visible UI and accessibility labels contain no retired Quick / Professional mode terminology.
- New, existing-with-last-view, existing-without-last-view, and stale-last-view navigation cases pass.
- Scene Canvas-first behavior, Candidate preview zero-write behavior, Formal confirmation/refetch behavior, and Shot switching remain green.
- 1440×900, 910×838, and 390×844 have no page-level horizontal overflow and preserve L1/L2 hierarchy.
- Frontend lint, typecheck, unit, API contract check, production build, E2E, `git diff --check`, retired-term scan, and 8080 formal-entry acceptance pass on the same current HEAD.

## Implementation evidence

### Current implementation

- Base: `dev@1b847ce319e886480f7bb2c7acd2c91744077df6` plus the uncommitted navigation-IA worktree.
- `WorkstationShell` is now the single global L1/L2 owner; `ProjectLobbyShell` is removed.
- Permanent L1 is `项目 / 创作 / 设置` across Lobby, Project, and Settings routes.
- Creative L2 is `剧本 / 资产 / 场景 / 制作 / 剪辑`; `/review` remains route-compatible but is presented under `制作 → 待审内容`.
- Project Lobby contains Project continuation, creation, search, and workspace filtering only. Provider configuration, workspace CRUD, and Project settings have moved to independent Settings routes.
- New settings routes: `/settings/account`, `/settings/workspaces`, `/settings/models`, `/settings/defaults`, and `/settings/projects/$projectId`.
- New Project still enters `/script`; existing Project cards enter the Project root; root restores a valid last view and otherwise redirects to `/scenes`.
- Product-visible retired Quick / Professional mode terminology scan is clean.
- Scene Canvas-first, Candidate / Formal, Production Monitor, Director, Review, and Editing business facts are unchanged.

### Verification

- `npm run lint`: PASS.
- `npm run typecheck`: PASS.
- `npm run test`: PASS — 26 files / 122 tests.
- `npm run format:check`: PASS.
- `npm run build`: PASS; `settings-page` is a separate lazy production chunk.
- `npm run test:e2e`: PASS — 17 Chromium tests, including new 1440×900 and 390×844 navigation IA coverage plus existing 910×838 Scene coverage.
- 8080 worktree image: `sha256:0238693592c9568cea5468aa6f9607b43b2d6720c608af72fcf3a31209c58b93`, labelled `worktree-20260904-navigation-ia`.
- 8080 HTTP: `/`, `/settings/defaults`, `/projects/demo/scenes`, `/gateway-health`, and `/health` all return 200; static gzip remains enabled.
- 8080 DOM assertions: stable three-item L1, context-correct L2, Lobby without Provider settings, independent Settings page, mobile five-item Creative L2, no page errors, and no horizontal overflow.
- `npm run api:check`: PASS using the formal 8080 backend's exported OpenAPI contract; generated API types remain unchanged.
- `git diff --check`: PASS.

### Remaining closeout condition

No commit was created in this implementation turn. The runtime image is intentionally labelled as a worktree build, not as the base Git SHA. NAV-7 and this contract must remain short of `COMPLETE` until the implementation is committed and the final gate is rebound to that exact current HEAD.

## 2026-09-07 Owner-authorized dev integration

The Owner subsequently requested “都合进dev”. The implementation and evidence above describe the earlier uncommitted handoff. Its remaining repository changes are now authorized for bounded commit/push into dev under [DEV-REMAINING-WORKTREE-INTEGRATION-20260907.md](DEV-REMAINING-WORKTREE-INTEGRATION-20260907.md), preserving other work and the original product/runtime/fee boundaries. Exact-head verification and actual commit facts are recorded by that closeout; this does not itself assert whole-Goal completion, a new deployment or formal release readiness.
