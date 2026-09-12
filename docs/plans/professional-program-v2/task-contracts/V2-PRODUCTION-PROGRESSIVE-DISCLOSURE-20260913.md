# Task: V2 — Production Progressive Disclosure

## Status

- **State:** IMPLEMENTED / VERIFIED; lifecycle superseded by `v2-production-progressive-disclosure-r2-20260913`
- **Task id:** `v2-production-progressive-disclosure-20260913`
- **Goal:** Continue the user-requested Computer Use UX optimization by restoring a clear Production overview hierarchy and reducing narrow-screen content overload without removing capabilities.
- **Boundary:** Production-page presentation, responsive disclosure, and directly related frontend tests only.

## Authority

- `01-DramaForge_专业版产品与开发最终方案_完整交互版.md` §89–90: Production owns cross-scene status and must not become a redundant second production page; avoid long explanatory copy.
- `02-DRAMAFORGE_PRO_DESIGN.md` §46: `/production` is the cross-scene Production Monitor while actual shot work belongs in Scene Workbench.
- `03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` §89: the old large storyboard workspace is not the Production page.
- `navigation-ia/DramaForge_统一导航与项目大厅信息架构设计方案.md` §8: Production organizes cross-scene work and Review remains an in-context view.

## Current Evidence / Drift

- Current-run Product Design / browser evidence at `390×844` shows the Production document at roughly `6,697px` high; the full 12-shot Workflow Navigator consumes about `1,534px` before the status summary appears.
- At `1440×900`, the page is roughly `4,723px` high and the first viewport is dominated by the shot-level workflow list, so the actual cross-scene status summary is not visible.
- The page begins with an `h2` and has no `h1`.
- The full Professional Workbench and a second pipeline rail are rendered inline after the cross-scene monitor, recreating the second-workbench effect the product authority explicitly rejects.
- The first after-build mobile screenshot exposed the six-column cross-scene table compressing Chinese headings into one-character-wide stacks; the table needs a contained, keyboard-focusable horizontal reading region rather than destructive column squeezing.
- Evidence: `tmp/ux-audit-20260913/03-production-mobile-top.png` and `04-production-desktop-top.png`.

## Outcome

- Production uses one `h1` and presents the cross-scene `ProductionMonitor` before shot-level tools.
- Workflow Navigator, Creative Capabilities, and the compatibility Professional Workbench remain available through labelled native disclosures.
- Disclosures default closed at `<=720px` and open on wider screens; users can toggle each independently, and viewport changes re-apply the responsive default.
- The selected-shot pipeline rail lives with the Professional Workbench rather than appearing as an unexplained duplicate at page level.
- Mobile status cards use a compact two-column grid and retain no page-level horizontal overflow.
- The cross-scene table keeps readable column widths inside its own labelled, keyboard-focusable horizontal scroll region; the page itself still does not overflow.

## Owned Paths

- `frontend/src/routes/production-page.tsx`
- `frontend/src/features/production/ProductionMonitor.tsx`
- `frontend/src/components/workstation/project-shell-visual.css`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- this Task Contract

## Non-scope

- No Project, Scene, Shot, Asset, Review, Experiment, Director, Provider, ProductionGraph, Candidate/Formal, EditSession, API, migration, or persisted-data semantics.
- No removal of Professional Workbench capabilities and no new route.
- No paid operation, Provider call, project mutation, or data deletion.

## Verification

- Focused E2E proves the Production `h1`, monitor-first order, narrow-screen closed defaults, disclosure toggling, two-column status layout, and no page-level horizontal overflow.
- Existing desktop professional workflow E2E continues to see the tools open by default.
- Frontend lint, typecheck, format, full unit, build, full E2E, and `git diff --check` pass.
- Rebuild the formal 8080 frontend and capture/inspect a current-run after screenshot at 390×844.

## Completion Evidence

- Implementation commits: `fe8574d` and `e536bb5`.
- Frontend lint, typecheck, format, 162 unit tests, production build, 22 E2E tests, and `git diff --check` passed.
- Formal frontend runtime image: `sha256:32fbbb88c3700044723b4ff82784e028ee7ebe1a26e99e1c68d2f0606399bdef`; `http://127.0.0.1:8080/healthz` returned 200.
- Current-run browser evidence: `tmp/ux-audit-20260913/06-production-mobile-final-top.png`, `07-production-mobile-final-table.png`, and `08-production-mobile-workflow-expanded.png`.
- At `390×844`, the document is `1,648px` high when tools are collapsed (down from roughly `6,697px`); one `h1` is present, the monitor precedes the disclosures, all three disclosures are closed, the first two status cards share a row, and document width equals client width.
- The `254px` labelled table region exposes a `600px` table, is focusable, reaches its `346px` maximum horizontal offset, and keeps the first scene-workspace action fully within the viewport at the right edge.
- The original ledger lifecycle was truthfully marked `FAILED` because the responsive table fix added `ProductionMonitor.tsx` after STARTED and owned paths are immutable. The replacement contract records the complete ownership boundary and formal closeout; no ledger history was rewritten.
