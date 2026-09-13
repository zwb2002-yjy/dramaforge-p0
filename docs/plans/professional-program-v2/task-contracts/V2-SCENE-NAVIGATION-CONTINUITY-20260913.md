# Task: V2 — Scene Navigation Continuity

## Status

- **State:** COMPLETE
- **Task id:** `v2-scene-navigation-continuity-20260913`
- **Goal:** Continue the user-requested Computer Use UX sweep by making Scene navigation truthful during loading, human-readable across workspaces, and less redundant on Production.
- **Boundary:** Frontend presentation and navigation affordances only. No Scene / Shot facts, API, persistence, production runtime, or paid operation changes.

## Authority

- `01-DramaForge_专业版产品与开发最终方案_完整交互版.md` §13–14, §88–90: one-click Scene overview, visual storyboard wall, Production as cross-scene organization rather than a duplicate workbench.
- `navigation-ia/DramaForge_统一导航与项目大厅信息架构设计方案.md` §5, §7–9: stable `剧本 → 资产 → 场景 → 制作 → 剪辑` navigation and truthful route transitions.
- Current formal runtime at `http://127.0.0.1:8080`, inspected through the Codex in-app browser.

## Current Evidence / Drift

- Navigating from Production to Scene overview initially renders `暂无场景` while `GET /scenes` is still pending, then replaces it with ten scene cards. The empty state is therefore false during the transition.
- Scene time values leak storage-oriented English (`dawn`, `morning`, `afternoon`, `dusk`, `blue hour`) on the storyboard wall, Scene Workspace, Production monitor, Workflow Navigator, and Script Workspace.
- Production renders both a per-scene table with a separate `场景工作区` action column and a second shot-chip strip. At the narrow in-app viewport the action is off-screen and visibly clipped, while the strip duplicates navigation already owned by the Scene workspaces.

## User-visible Outcome

1. Scene overview shows a neutral loading status until the request resolves; `暂无场景` appears only after a successful empty response.
2. Known time-of-day values are displayed in Chinese on all scene-oriented surfaces while unknown/user-authored values are preserved.
3. Production scene names are the direct workspace links; the separate action column and redundant shot-chip strip are removed.
4. Production summary facts and all underlying navigation targets remain unchanged.

## Owned Paths

- `frontend/src/lib/sceneLabels.ts`
- `frontend/src/features/scenes/SceneStoryboardWall.tsx`
- `frontend/src/features/scenes/SceneWorkspace.tsx`
- `frontend/src/features/production/ProductionMonitor.tsx`
- `frontend/src/features/production/WorkflowNavigator.tsx`
- `frontend/src/features/script/ScriptWorkspace.tsx`
- `frontend/src/components/workstation/project-shell-visual.css`
- `frontend/tests/unit/sceneLabels.test.ts`
- `frontend/tests/unit/SceneStoryboardWall.test.tsx`
- `frontend/tests/unit/ProductionMonitor.test.tsx`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- this Task Contract

## Non-scope / Safety Boundary

- No API, schema, generated client, migration, Scene / Shot / Artifact fact, Candidate/Formal gate, ProductionGraph, NodeRun, Provider, editing, or route-ownership change.
- No scene copy/reorder semantics are removed; destructive structural actions retain their existing confirmation boundaries.
- No project mutation, data deletion, Provider call, paid generation, upload, or external transmission.

## Verification

- Focused: scene-label unit tests; SceneStoryboardWall unit tests; ProductionMonitor unit tests; navigation IA E2E.
- Required regression: frontend typecheck, lint, format check, full unit suite, production build, full E2E suite, and `git diff --check`.
- Runtime: rebuild/restart the formal frontend container, verify `/healthz`, then re-walk Production → Scene overview → Scene Workspace in the original in-app browser tab.

## Completion Conditions

- User-visible outcomes above are verified against the formal 8080 runtime.
- Required tests pass, changed paths stay inside this contract, source and closeout are committed, and the local ledger records `COMPLETED` at the exact commit.

## Completion Evidence

- Implementation commit: `fc4fa62 fix(frontend): streamline scene navigation`.
- Scene overview now renders `正在读取场景…` while the scene query is pending and renders the empty state only after a successful empty result. Unit coverage resolves a controlled pending request and verifies both states.
- `timeOfDayLabel` humanizes the persisted scene-time vocabulary while preserving unknown/user-authored values; the storyboard wall, Scene Workspace, Production monitor, Workflow Navigator, and Script Workspace all consume the same label boundary.
- Production scene names now link directly to their existing Scene Workspace URLs. The separate action column and duplicate shot-chip strip are absent; summary counts and destination routes are unchanged.
- Focused verification: typecheck passed; SceneStoryboardWall and ProductionMonitor unit tests passed (6 tests); navigation IA E2E passed (5 tests).
- Required regression: lint passed; format check passed; production build passed; the full unit suite passed in deterministic single-worker mode (29 files / 163 tests); the full Playwright suite passed (23 tests); `git diff --check` passed. The default parallel unit run exposed the pre-existing NavigationTransitions one-second mount timeout, while that file passed in isolation and the complete deterministic suite passed.
- Formal runtime: frontend rebuilt and restarted as `sha256:1428a96062b3728391bcb08a9e086a0aef922566f6255eb6bf73527c1701732a`; `dramaforge-frontend-1` reached `healthy`; `/healthz` returned 200.
- In-app browser verification on the original project tab: the first Scene-overview state visibly contained `正在读取场景…` and no false empty message; the resolved state contained all ten scenes with Chinese times from `拂晓` through `蓝调时刻`; Production contained ten scene-name links, five table columns, no `进入` column and no duplicate shot strip; clicking the first scene name landed on the correct Scene Workspace, whose context displayed `1.1 · 拂晓`.
- No project mutation, data deletion, paid operation, Provider call, upload, or external transmission occurred.
