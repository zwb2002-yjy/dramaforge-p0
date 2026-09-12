# Task: V2 — Review Mobile Canvas Containment

## Status

- **State:** COMPLETE
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

- Implementation commit: `e721f96` (`fix(frontend): contain review canvas on mobile`).
- `MediaReviewCanvas` now uses module-owned semantic classes for the containing block, image, and region overlay; no undefined utility class is required.
- Unit coverage preserves normalized point/region callbacks and asserts the semantic canvas/image/region hooks.
- Mobile E2E starts from Production, navigates to Review, loads a `736×1312` fixture, and proves responsive containment, preserved aspect ratio, normalized region geometry, and zero page/main overflow.
- Full frontend verification passed: lint, typecheck, format check, 29 unit files / 162 tests, production build, 23 E2E tests, and `git diff --check`.
- Formal runtime: `dramaforge-frontend-1` healthy; `/healthz` returned 200; image `sha256:c70c58b45cb974a14c09a4643b148cd6c78feccfa777099548bc2da892881619`.
- Current real-project browser at `390×844`: canvas and image are both `296×527.640625px` from a `736×1312` source; image right edge is `368px` inside the `384px` document; main `scrollWidth=clientWidth=328`; rendered ratio `0.5609879` matches natural ratio `0.5609756`.
- The responsive image reduces the current Review document from `2,826px` before to `2,036px` after, and Review → Production navigation returns to the production monitor successfully.
- Screenshot: `tmp/ux-audit-20260913/09-review-mobile-final-canvas.png`, `390×844`, `330,175` bytes, SHA-256 `7659ee7a9e437736c91bef2d62ea71f517d37b7b0cb4c1de9afac9e9f658a28e` (retained as automated evidence; not passed to `view_image` because it exceeds the repository's 200 KiB inspection limit).
- No annotation API, persisted data, video behavior, paid operation, Provider call, project mutation, or deletion changed.
