# Task: V2 — Editing Human-Readable Timeline

## Status

- **State:** COMPLETE
- **Task id:** `v2-editing-human-readable-timeline-20260913`
- **Goal:** Continue the user-requested in-app-browser UX cleanup by removing internal identifiers and contradictory empty-state wording from the normal Edit handoff page.
- **Boundary:** Read-only Edit handoff presentation and directly related frontend tests only.

## Authority

- `03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` §80–86: the Edit handoff is built from formal production clips and preserves production lineage.
- `P9-OPENCUT-EDITING.md`: the formal-shot timeline is a human-operated editing handoff; data lineage remains unchanged.
- `ACCEPTANCE-A01-EDITING-RECOVERY-20260906.md`: existing sessions must be discoverable and explicitly reopened; normal entry must not imply they disappeared or create one implicitly.

## Current Evidence / Drift

- Current in-app-browser evidence shows two existing EditSessions, while the page heading says “还没有可编辑的剪辑会话”.
- Every read-only timeline row exposes raw scene UUID, shot UUID, and artifact UUID. These are implementation details rather than editing decisions and dominate the narrow in-app browser.
- The formal manifest already supplies timeline order and shot numbers, so the preview can remain traceable without exposing raw identifiers.

## Outcome

- The no-selected-session heading neutrally explains that users can continue an existing session or explicitly create a new one.
- Formal timeline rows use human-readable clip order, shot number, compact time range, and delivery state.
- Raw scene, shot, and artifact identifiers remain in the underlying manifest and production lineage but are not rendered in the normal read-only preview.

## Owned Paths

- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/tests/unit/EditingWorkspace.test.tsx`
- `frontend/tests/e2e/professional-edit.spec.ts`
- this Task Contract

## Non-scope

- No EditSession selection, creation, timeline editing, save, export, Final Film, Director suggestion, API, data model, persisted fact, Provider call, paid operation, project mutation, or deletion semantics.
- No removal of traceability from backend data or evidence views.

## Verification

- Unit and E2E coverage prove human-readable rows, identifier suppression, neutral session wording, and the unchanged explicit-create flow.
- Frontend lint, typecheck, format, full unit, build, full E2E, and `git diff --check` pass.
- Rebuild the formal 8080 frontend and verify the real project through the original Codex in-app-browser tab.

## Completion Evidence

- Implementation commit: `7d2e3be` (`fix(frontend): humanize editing timeline`).
- The normal handoff copy now states that the current view is read-only and offers either continuing an existing session or explicitly creating a new one; it no longer claims no session exists.
- Timeline rows render compact ranges, sequence (`片段 N`), manifest shot number (`镜头 #N`), and `正式素材已交付` / `正式素材待交付` / `未绑定正式素材` rather than scene, shot, or artifact IDs.
- Unit coverage verifies the human-readable row, identifier suppression, neutral copy, and delivery-state refresh. The existing E2E verifies the same presentation and then completes the unchanged explicit create/edit/save/reopen/export/suggestion chain.
- Full frontend verification passed: lint, typecheck, format check, 29 unit files / 162 tests, production build, 23 E2E tests, and `git diff --check`.
- Formal runtime: `dramaforge-frontend-1` healthy; `/healthz` returned 200; image `sha256:8ff3d8547bb47ff4b668b0f7b078bf1947f6220ccdd3de055887707a4f52e32a`.
- Codex in-app browser verification on the real project shows both existing sessions, the neutral handoff copy, ten human-readable timeline rows (`0–5 秒 · 片段 1 · 镜头 #1` through `45–50 秒 · 片段 10 · 镜头 #12`), and no rendered scene/shot/artifact UUIDs.
- No EditSession, timeline, production lineage, persisted data, API, Provider, paid operation, project mutation, or deletion semantics changed.
