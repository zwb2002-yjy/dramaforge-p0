# Task: P9-03A — Editing Session HTTP Lifecycle

## Status

- **State:** COMPLETE
- **Program order:** P9-00/P9-01/P9-02（已完成）→ **P9-03A Editing Session HTTP（本任务）** → P9-03 Editing Workspace UI
- **Task id:** `p9-03a-editing-session-http`
- **Task boundary:** Expose the existing `EditingAdapter` and
  `build_edit_session_for_project` through project-scoped HTTP routes.  This
  task does not wire the `/edit` frontend, add editing UI, or change production
  truth.

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`P9-OPENCUT-EDITING.md`](P9-OPENCUT-EDITING.md) Phase 9 boundary
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §22 Phase 9
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §80–§86
- Existing `backend/app/editing/adapter.py` and `timeline_builder.py`

## Current evidence / drift

- `EditSession` persistence, `EditingAdapter` lifecycle methods, and the
  formal-production timeline builder already exist.
- The adapter had no project-scoped HTTP registration; `/edit` remains a
  readonly manifest shell.
- `EditSession.production_lineage` is production-owned readonly provenance and
  must not be accepted by timeline writes.

## Implementation

- `POST /projects/{project_id}/edit-sessions` checks project ownership and
  builds a session from current formal production facts, then commits only the
  new `EditSession` row.
- `GET /projects/{project_id}/edit-sessions/{session_id}` loads a project-owned
  session and returns timeline plus readonly lineage.
- `PATCH /projects/{project_id}/edit-sessions/{session_id}/timeline` accepts
  only the JSON-safe editable timeline (`clips` and `metadata`), rejects
  `production_lineage`, uses CSRF and `EditingAdapter.save_timeline`, and
  commits only the edit session timeline.
- `GET /projects/{project_id}/edit-sessions/{session_id}/export` returns the
  adapter's read-only manifest; it does not render, create artifacts, inspect
  provider rows, or dispatch execution.
- Every route uses selected-workspace dependency and project ownership checks;
  session IDs are always constrained by `project_id`.

## Explicitly out of scope

- `/edit` frontend wiring, drag/drop, or timeline editor UI.
- OpenCut manifest changes or a second timeline model.
- `Shot.formal_*_artifact_id`, `Asset.current_version_id`, ProductionGraph,
  NodeRun, ProviderOperation, Artifact, Worker, Runtime, or Provider changes.
- Director/P9-04 suggestions, proposals, or automatic edits.

## Owned paths

- `backend/app/api/v1/editing.py`
- `backend/app/api/v1/router.py`
- `backend/tests/unit/test_editing_api.py`
- `docs/plans/professional-program-v2/task-contracts/P9-03A-EDITING-SESSION-HTTP.md`

## Verification gate

- Focused API tests prove create/build, save/reopen, export, CSRF, project
  isolation, lineage rejection, and unchanged formal production facts.
- Existing Phase 9 adapter gate remains green.
- `ruff`, `mypy app`, generated API check/typecheck, and `git diff --check`
  pass (with any generated OpenAPI diff attributable only to this route).
