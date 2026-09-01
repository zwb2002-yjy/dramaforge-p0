# Task: P10 — Scene/Shot Workbench UI Recomposition

## Status

- **State:** COMPLETE
- **Task id:** `p10-scene-shot-workbench-ui-recomposition`
- **Program order:** Phase 10 UI consolidation / V1 gate → **Scene/Shot Workbench UI recomposition**
- **Boundary:** Recompose the existing Scene Workbench around a stage-first canvas while preserving the canonical `SceneWorkspaceRead → selectedShot → existing API` fact chain.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) — canvas-first workbench and scene layout
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) — Scene Workbench, ShotStrip, candidate and formal-line boundaries
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) — Scene/Shot/Canvas as creative truth
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) — Phase 10 UI consolidation and V1 flow
- [`P10-UI-CONSOLIDATION.md`](P10-UI-CONSOLIDATION.md) — `/production` monitor and shell boundaries

## Current evidence / drift

- `SceneWorkspace` currently renders a left vertical ShotStrip, a central canvas, and a right sidebar with design, references, production, formal confirmation, and trace all stacked together.
- `CinematicCanvas` gives formal media precedence over server candidates and has no local candidate-selection state.
- `ShotFormalOutputActions` owns candidate parsing and confirmation in the right sidebar.
- `ProjectWorkspaceShell` always receives the outer EvidenceInspector from the project route, so Scene Workbench has two right-side surfaces and an unnecessary outer width cap.
- The backend already exposes concrete NodeRun → Artifact candidates and the existing formal selection endpoints; no backend or schema change is needed.

## Required result

1. Add a strict `shotCandidates.ts` parser that accepts only concrete image/video Artifact lineage rows with stage/media agreement and rejects opaque ExperimentBranch rows.
2. Add `ShotCandidateTray` below the canvas. Candidate clicks are local preview selection only; formal confirmation calls only the existing `setShotFormalKeyframe` / `setShotFormalVideo` APIs with the exact current `shot.version` and fails closed on stale errors.
3. Make `CinematicCanvas` candidate-preview aware with priority: local candidate, formal video, formal keyframe, unconfirmed candidate, execution state, placeholder. It must not render prompt controls and must clear preview on Shot changes/refetch after confirmation.
4. Make `ShotStrip` a bottom horizontal storyboard/timeline hybrid displaying formal keyframe, number, duration, type, formal status, and trace risk.
5. Make `DirectorSidebar` a compact collapsible tabs surface: 镜头 (design + suggestion), 参考 (asset picker), 生成 (production actions + trace). Formal confirmation does not live in this sidebar.
6. Compose Scene Workbench as compact header + stage (canvas / candidates / strip) + one right operation panel, and suppress the outer project EvidenceInspector for `view === "scenes"` only.
7. Update focused unit/E2E tests and the bounded manual professional flow; no new Candidate/Shot Store/snapshot or production command is introduced.

## Allowed paths

- `frontend/src/features/shots/CinematicCanvas.tsx`
- `frontend/src/features/shots/shotCandidates.ts`
- `frontend/src/features/shots/ShotCandidateTray.tsx`
- `frontend/src/features/shots/ShotStrip.tsx`
- `frontend/src/features/director/DirectorSidebar.tsx`
- `frontend/src/features/scenes/SceneWorkspace.tsx`
- `frontend/src/components/workstation/ProjectWorkspaceShell.tsx`
- `frontend/src/components/workstation/project-shell.css`
- `frontend/src/routes/projects.$projectId.tsx`
- `frontend/tests/unit/**` (focused Scene/Shot/Workstation tests)
- `frontend/tests/e2e/professional-manual.spec.ts`
- `frontend/tests/e2e/professional-mocks.ts`
- this Task Contract

## Forbidden paths and behavior

- Do not modify Scene/Shot ORM, backend API/schema, migrations, Provider, Runtime, Worker, ProductionGraph, NodeRun, ExecutionModelResolver, or OpenCut.
- Do not add `ProfessionalShot`, a Candidate table, Shot Store, project-wide snapshot, or new `/production` generation/candidate operations.
- Do not make candidate clicks or preview selection API mutations.
- Do not move formal confirmation into a second implementation; reuse the existing formal endpoints and optimistic-lock version contract.
- Do not commit or alter the untracked `codex-with-chatgpt/` directory.

## Verification gate

- Focused Vitest coverage proves canvas priority/Shot reset, CandidateTray local click and exact formal URL/body/version/stale handling, ShotStrip bottom semantics, tab isolation, selected-shot references and generation, and Scene shell outer-inspector behavior.
- `npm run lint`, `npm run typecheck`, `npm run test`, `npm run api:check`, `npm run build`, `npm run test:e2e`, and `git diff --check` pass, subject to any explicitly recorded environment blocker.
- Focused and full frontend gates passed on the task branch; commit and push this branch for root review; do not merge `dev`.

## Evidence

- `npm run lint` — passed with the two pre-existing Fast Refresh warnings.
- `npm run typecheck` — passed.
- `npm run test` — 34 files / 136 tests passed.
- `npm run api:check` — passed; generated API types unchanged.
- `npm run build` — passed.
- `npm run test:e2e` — 16 Chromium tests passed.
- `git diff --check` — passed.
