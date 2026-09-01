# Task: P10 — Visual 2.2 Studio Theme

## Status

- **State:** COMPLETE
- **Task id:** `p10-ui-visual-studio-theme`
- **Program order:** P10 Visual 2.1 refinement → **Visual 2.2 studio theme**
- **Boundary:** Reframe the existing project workstation as a warm paper/graphite studio surface while preserving every creative, Scene/Shot, Asset, production and API fact.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) — canvas-first/media-first product principles
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) — Scene Workbench and shell structure
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) — Scene/Shot/Canvas as creative truth
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) — Phase 10 release boundary
- [`P10-UI-VISUAL-REFINEMENT.md`](P10-UI-VISUAL-REFINEMENT.md) — preceding project-shell visual layer

## Current evidence / drift

- Visual 2.1 made the project pages structurally consistent, but the inherited dark token values still made the real project shell read as an AI admin console rather than a professional film studio.
- Quick Creation intentionally shares historical `qc-*` class names and screenshot baselines, so project-page visual changes must be scoped and must not leak into the preview shell.
- Scene already has the required Canvas → CandidateTray → ShotStrip → single right operation panel hierarchy; this task changes only surfaces, contrast, spacing and presentation language.

## Studio theme goals

- Use a warm gray/paper application workspace with a quiet graphite navigation rail and a graphite media Canvas; use restrained copper/brass and verdigris for action/state emphasis.
- Keep 4–8px radii, 1px rules, compact toolbars and clear whitespace; remove purple-black AI styling, decorative gradients, glow, oversized serif headings and long explanation blocks.
- Keep the Scene Canvas largest, CandidateTray and ShotStrip as lightweight media bands, and the right tabs as a light compact inspector. Scene has no outer EvidenceInspector; production/assets and other views retain it.
- Present product-facing states (`正在生成`, `已完成`, `需要确认`, `正式`, `实验`) before technical ids, which remain secondary metadata.
- Preserve accessibility: readable contrast, focus rings, tab semantics, disabled states, and no horizontal overflow at 1440×900 and 910×838.

## Owned paths

- `frontend/src/components/workstation/project-shell-visual.css`
- `frontend/src/components/workstation/ProjectWorkspaceShell.tsx`
- `frontend/src/styles/index.css` (audited; no unrelated global rewrite)
- `frontend/src/features/assets/AssetCardsPanel.tsx`
- `frontend/src/features/production/ProductionMonitor.tsx`
- `frontend/src/features/scenes/SceneWorkspace.tsx`
- `frontend/src/features/director/DirectorSidebar.tsx`
- `frontend/src/features/shots/ShotCandidateTray.tsx`
- `frontend/src/features/shots/ShotStrip.tsx`
- `frontend/tests/e2e/professional-manual.spec.ts`
- this Task Contract

## Out of scope

- No Scene/Shot/Asset/Runtime facts, API/schema, ORM, DB/migration, Provider, Worker, Graph, NodeRun, ExecutionModelResolver, OpenCut, route, generation or persistence changes.
- No second global token system; local project-shell overrides consume the existing `--df-*` variables.
- No Quick Creation redesign or screenshot baseline update.
- Do not touch `codex-with-chatgpt/` or unrelated untracked files.

## Implementation evidence

- `project-shell-visual.css` now supplies scoped local light-studio values: paper application surfaces, graphite navigation/media stage, copper/brass actions and verdigris success states. It is loaded by the real `ProjectWorkspaceShell`; Quick Creation remains outside the scope.
- Shell, page primitives, assets, production, script, review and editing surfaces share compact border/radius/type rhythm. Asset status and shell mode labels are product-facing; technical values stay in metadata/title context.
- Scene stage contrast and media bands are retained while nested card chrome is reduced; the one right operation panel and candidate/formal behavior are unchanged.
- DOM assertions cover scope-root colors, dark Canvas contrast, 1440×900 central-vs-right width, 910×838 Scene stacking, no page overflow, Scene inspector absence, and production/assets inspector retention. Existing Quick Creation screenshot baselines remain green.

## Verification

- Focused `professional-manual.spec.ts` — 3 Chromium tests passed.
- `npm run lint` — passed with two pre-existing Fast Refresh warnings.
- `npm run typecheck` — passed.
- `npm run test` — 34 files / 138 tests passed.
- `npm run api:check` — passed; generated API types unchanged.
- `npm run build` — passed.
- `npm run test:e2e` — 17 Chromium tests passed, including Quick Creation screenshot baselines and Scene 1440×900 / 910×838 assertions.
- `git diff --check` — passed.
