# Task: V2 — Editing Human-Readable Timeline

## Status

- **State:** READY / NOT STARTED
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

- Pending implementation.
