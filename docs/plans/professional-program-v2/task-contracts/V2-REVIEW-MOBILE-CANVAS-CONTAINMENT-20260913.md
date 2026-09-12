# Task: V2 — Review Mobile Canvas Containment

## Status

- **State:** READY / NOT STARTED
- **Task id:** `v2-review-mobile-canvas-containment-20260913`
- **Goal:** Continue the user-requested Computer Use UX optimization by making the Review keyframe fully visible and annotatable inside narrow project workspaces.
- **Boundary:** Review image-canvas presentation and directly related frontend regression tests only.

## Authority

- `03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` §53–55: Review owns image-region and video-time annotation interactions.
- `P6-REVIEW-UI.md`: normalized image annotations must render and remain interactive; the canvas is presentational and must preserve 0..1 coordinate behavior.
- Current browser evidence at `390×844` is the implementation baseline.

## Current Evidence / Drift

- Production → Review navigation succeeds, but the `736×1312` formal keyframe renders at its full `736px` CSS width inside a `296px` content column.
- The Review main surface reports `scrollWidth=752` over `clientWidth=328`; the shell clips the excess, leaving more than half of the image and annotation surface unreachable.
- `MediaReviewCanvas` uses utility-like class names (`relative`, `inline-block`, `max-w-full`, `absolute`, and border utilities) that have no definitions in the current stylesheet stack, so neither responsive containment nor annotation overlay positioning is guaranteed.

## Outcome

- The review canvas uses owned semantic classes and scales down to its available column while preserving the source aspect ratio and normalized coordinate system.
- Annotation regions remain absolutely positioned over the rendered image with the existing focus-ring token.
- The component does not upscale a smaller source image beyond its intrinsic width.
- Mobile Review keeps the image and canvas fully within the content viewport with no main-surface overflow.

## Owned Paths

- `frontend/src/features/review/MediaReviewCanvas.tsx`
- `frontend/src/features/review/video-review.css`
- `frontend/tests/unit/ReviewUI.test.tsx`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- this Task Contract

## Non-scope

- No annotation API, normalized-coordinate semantics, saved data, video playback, repair workflow, Provider call, paid operation, project mutation, or data deletion.
- No Review information-architecture redesign or unrelated page cleanup.

## Verification

- Unit coverage asserts semantic canvas/image/region classes and preserves point/region coordinate callbacks.
- Mobile E2E proves Review navigation, canvas/image containment, preserved image aspect ratio, and no Review main-surface overflow.
- Frontend lint, typecheck, format, unit, build, full E2E, `git diff --check`, formal 8080 rebuild, and current-run browser assertions pass.

## Completion Evidence

- Pending implementation.
