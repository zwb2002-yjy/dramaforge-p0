# Task: P10 — Visual 2.1 Workstation Refinement

## Status

- **State:** COMPLETE
- **Task id:** `p10-ui-visual-refinement`
- **Program order:** P10 Scene/Shot Workbench UI recomposition and version parity → **Visual 2.1 refinement**
- **Boundary:** Improve the visual hierarchy, spacing, typography, surfaces, and responsive layout of the existing professional workstation without changing creative/production facts.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) — professional canvas-first product principles
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) — Scene Workbench and shell visual structure
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) — Scene/Shot/Canvas as creative truth
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) — Phase 10 release and UI consolidation boundary
- [`P10-SCENE-SHOT-WORKBENCH-UI-RECOMPOSITION.md`](P10-SCENE-SHOT-WORKBENCH-UI-RECOMPOSITION.md) — current Scene Workbench composition and evidence

## Current evidence / drift

- The deployed workstation is functionally stage-first, but `project-shell.css` and `src/styles/index.css` still expose a mixed legacy/Visual 2.0 vocabulary (`.panel`, `.status-card`, `.callout`, `.qc-*`) with inconsistent borders, radii, shadows, typography and vertical rhythm.
- Project shell navigation/top bar/content/inspector do not share a clear density scale at 1440×900 and 910×838; page content can feel boxed-in while the evidence inspector competes with the page heading.
- Scene Workbench has the correct Canvas → CandidateTray → ShotStrip → right tabs responsibilities, but the visual grouping uses too many nested rounded cards and weakly differentiated stage/media/status layers.
- Asset, production, review, editing and script views consume the same legacy classes but lack a coherent page heading, control, status badge, list/table and empty-state hierarchy.

## Visual 2.1 goals

- Preserve a neutral deep workspace with restrained brass/verdigris emphasis; no purple, gradients, glow, or decorative chat-bubble treatment.
- Establish a shared shell/page rhythm: compact top bar, predictable content max-width, calm borders, small radius, readable line lengths, and one clear primary action per region.
- Keep the Scene Canvas largest, CandidateTray directly below it, ShotStrip at the bottom, and the right operation panel at 340–380px; collapsed operation panel must widen the stage.
- Use product-facing status language first (`正在生成`, `已完成`, `需要确认`, `正式`, `实验`) and demote technical ids to metadata styling.
- Make 1440×900 and 910×838 readable with no horizontal page overflow; preserve Scene's single right panel and other views' outer EvidenceInspector.

## Allowed paths

- `frontend/design/tokens.css` (only if a missing shared token is required; prefer existing tokens)
- `frontend/src/styles/index.css`
- `frontend/src/components/workstation/ProjectWorkspaceShell.tsx`
- `frontend/src/components/workstation/project-shell.css`
- `frontend/src/components/workstation/project-shell-visual.css`
- `frontend/src/features/scenes/SceneWorkspace.tsx`
- `frontend/src/features/director/DirectorSidebar.tsx`
- `frontend/src/features/shots/ShotCandidateTray.tsx`
- `frontend/src/features/shots/ShotStrip.tsx`
- `frontend/src/features/assets/AssetCardsPanel.tsx`
- `frontend/src/features/production/ProductionMonitor.tsx`
- focused frontend DOM/layout tests and relevant E2E assertions
- this Task Contract

## Forbidden changes

- Do not change Scene/Shot/Asset/Runtime facts, API/schema, ORM, DB/migration, Provider, Worker, Graph, NodeRun, ExecutionModelResolver, OpenCut, generation semantics, or routes.
- Do not introduce a second token system or duplicate business state.
- Do not alter `codex-with-chatgpt/` or unrelated untracked files.
- Do not replace DOM/layout verification with screenshots; any screenshot is bounded QA evidence only.

## Verification gate

- DOM/layout assertions cover 1440×900 and 910×838, no horizontal overflow, Scene no outer inspector/one right operation panel/four stage regions, and production/assets retaining the outer EvidenceInspector.
- `npm run lint`, `npm run typecheck`, `npm run test`, `npm run api:check`, `npm run build`, `npm run test:e2e`, and `git diff --check` pass.
- Commit and push a review branch and create a PR for root review; do not merge `dev`.

## Implementation evidence

- Added a project-only Visual 2.1 layer in
  `frontend/src/components/workstation/project-shell-visual.css`; it consumes
  the existing `--df-*` tokens and is imported by `ProjectWorkspaceShell`.
  The shared `project-shell.css`, design-preview Quick shell, and global token
  files remain behavior-compatible.
- Refined project navigation/top bar/content and inspector rhythm; Scene keeps
  Canvas → CandidateTray → ShotStrip → one right operation panel, while the
  outer inspector remains available to production/assets and other project
  views.
- Unified project-page panels, controls, status cards, tables, asset cards,
  script/review/editing surfaces, and production sub-surfaces around neutral
  obsidian/ink surfaces with restrained brass/verdigris states. Technical
  asset status and shell mode labels now present product-facing language first.
- Added 1440×900 and 910×838 DOM/layout assertions for no horizontal overflow,
  Scene four-region hierarchy, central-vs-right width, responsive stacking,
  and production/assets inspector retention. Quick Creation screenshot
  baselines remain unchanged.

## Verification

- Focused `professional-manual.spec.ts` — 3 Chromium tests passed.
- `npm run lint` — passed with two pre-existing Fast Refresh warnings.
- `npm run typecheck` — passed.
- `npm run test` — 34 files / 138 tests passed.
- `npm run api:check` — passed; generated API types unchanged.
- `npm run build` — passed.
- `npm run test:e2e` — 17 Chromium tests passed, including both Visual 2.1
  Scene layout viewports and unchanged Quick screenshot baselines.
- `git diff --check` — passed.
