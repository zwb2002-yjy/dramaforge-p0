# Task: P9-03B — Editing Workspace Session UI

## Status

- **State:** COMPLETE
- **Program order:** P9-03A Editing Session HTTP（已完成）→ **P9-03B Editing Workspace Session UI（本任务）** → 后续编辑器能力
- **Task id:** `p9-03b-editing-workspace-session-ui`
- **Task boundary:** Connect `/projects/$projectId/edit` to the persisted
  `EditSession` HTTP lifecycle.  Keep the no-session view as a read-only
  formal OpenCut manifest preview and keep production truth immutable.

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`P9-OPENCUT-EDITING.md`](P9-OPENCUT-EDITING.md) Phase 9 boundary
- [`P9-03A-EDITING-SESSION-HTTP.md`](P9-03A-EDITING-SESSION-HTTP.md)
- Existing `frontend/src/features/editing/EditingWorkspace.tsx`
  and `frontend/src/routes/projects.$projectId.edit.tsx`

## Current evidence / drift

- The route previously rendered only the read-only OpenCut formal manifest and
  had no session identity in the URL.
- P9-03A now exposes create/load/save/export for the existing backend
  `EditingAdapter`; this task consumes those generated API contracts without
  adding another DTO or timeline truth.

## Implementation

- `frontend/src/features/editing/api.ts` reuses generated `EditSessionRead`,
  `EditTimelinePayload`, and `EditExportRead` types with existing `apiGet`,
  `apiSend`, and CSRF handling.
- `?sessionId=<id>` is the only persisted-session identity.  Creation is an
  explicit POST followed by route navigation to that exact id; no
  local/session storage or implicit latest-session lookup is used.
- No session: show the formal OpenCut manifest preview and an explicit create
  button; never auto-create or fabricate editable state.
- With a session: load the exact server session, display name/id/status and
  read-only production lineage, and keep a local draft that only moves clips
  or edits `duration_seconds` while preserving all other clip fields.
- Save is explicit and sends only `{timeline: {clips, metadata}}`; success
  replaces the local clean baseline with the server response, while failures
  retain the dirty draft. Export is a read-only summary (`format`,
  `clip_count`, `duration_seconds`) and never renders media.

## Explicitly out of scope

- Drag/drop, multi-track editing, audio/subtitle/effects, media rendering, or
  OpenCut manifest changes.
- Changes to Shot/Asset/ProductionGraph/NodeRun/Provider/Runtime truth.
- P9-04 Director editing suggestions or any autosave.

## Owned paths

- `frontend/src/features/editing/api.ts`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/src/routes/projects.$projectId.edit.tsx`
- `frontend/tests/unit/EditingWorkspace.test.tsx`
- `frontend/src/shared/api/generated.ts` (generated only)
- `docs/plans/professional-program-v2/task-contracts/P9-03B-EDITING-WORKSPACE-SESSION-UI.md`

## Verification gate

- Focused EditingWorkspace tests cover no-session read-only behavior and no
  auto-create, explicit create/CSRF/navigation, exact session load, local-only
  edit/dirty state, allow-listed save payload, reopen, export summary, and
  failed-save dirty preservation.
- Full frontend Vitest, typecheck, lint, build, generated API check, and
  `git diff --check` pass (with generated OpenAPI changes attributable only to
  P9-03A).
