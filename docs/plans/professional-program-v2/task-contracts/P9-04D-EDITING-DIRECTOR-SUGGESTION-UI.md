# Task: P9-04D — Editing Director Suggestion Preview UI

## Status

- **State:** COMPLETE
- **Program order:** P9-04C Editing Director Suggestion HTTP Bridge（已完成）→ **P9-04D Editing Director Suggestion Preview UI** → 后续编辑器能力
- **Task id:** `p9-04d-editing-director-suggestion-ui`
- **Task boundary:** 在现有 `/projects/$projectId/edit` 的 persisted
  `EditingWorkspace` 内消费 P9-04C，提供一次显式的 Director 建议请求和只读
  proposal preview。建议保持为 pending proposal；已应用 timeline 与预览状态必须
  分离。

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`P9-03A-EDITING-SESSION-HTTP.md`](P9-03A-EDITING-SESSION-HTTP.md) — session HTTP and CSRF
- [`P9-03B-EDITING-WORKSPACE-SESSION-UI.md`](P9-03B-EDITING-WORKSPACE-SESSION-UI.md) — existing editor/session boundary
- [`P9-04A-EDITING-PROPOSAL-APPLY.md`](P9-04A-EDITING-PROPOSAL-APPLY.md) — versioned typed command boundary
- [`P9-04B-EDITING-DIRECTOR-SUGGESTION.md`](P9-04B-EDITING-DIRECTOR-SUGGESTION.md) — deterministic proposal service
- [`P9-04C-EDITING-DIRECTOR-SUGGESTION-HTTP.md`](P9-04C-EDITING-DIRECTOR-SUGGESTION-HTTP.md) — exact HTTP request/response contract
- Existing `frontend/src/features/editing/EditingWorkspace.tsx`, `api.ts`, and unit tests

## Current evidence / drift

- P9-04C already exposes a project/session-scoped POST accepting only
  `expected_session_version` and `user_instruction`, returning exact
  `proposal_id`, `item_id`, and a typed candidate.
- The existing workspace already owns the route project/session identity, persisted
  EditSession load, manual local editing, explicit timeline save, reopen, and export.
- No frontend suggestion request wrapper or preview state exists yet.

## Implementation contract

1. **Typed API boundary.** Add a typed P9-04C POST wrapper in
   `frontend/src/features/editing/api.ts`, using the existing workspace headers,
   `fetchCsrf`, and `apiSend` convention. The wrapper sends only the current
   `expected_session_version` and non-blank `user_instruction`; project/session
   identity comes only from its route arguments.
2. **Explicit preview state.** In `EditingWorkspace`, add independent instruction,
   request/pending, error, and pending-proposal preview state. Submit the loaded
   session's current `version` and current `projectId`/`sessionId`; render the exact
   proposal/item IDs, typed operations, and rationale/benefit/cost/risk/impact.
   Pending preview must not be represented as an applied timeline or timeline event.
3. **Staleness and race safety.** When the server session `version` changes, mark
   an existing preview stale and disable its use as current preview; when route
   identity changes, clear the preview to preserve project/session isolation. Do
   not silently retry or change/save the timeline. Require an explicit new
   request. Disable duplicate submission and guard asynchronous responses so an old
   response cannot overwrite a newer request or session state.
4. **Fail closed.** Empty/blank instructions never submit. Surface 409/403/404/422
   errors as errors without fallback data, and never call timeline save for suggestion
   failures or previews. Preserve existing manual editing, explicit save, reopen,
   and export behavior.
5. **Tests and styling.** Extend `frontend/tests/unit/EditingWorkspace.test.tsx`
   with focused API/UI/fact-preservation coverage for request version and body
   boundary, exact IDs/operations/explanations, separation from applied timeline,
   version staleness, 409/403/404/422, blank input, and in-flight races. Add only
   minimal editing preview styles to `frontend/src/styles/index.css`.

## Explicitly out of scope

- Backend routes, schemas, generated API edits unless `api:check` proves them stale.
- Apply/accept/reject/partial-apply controls or any automatic timeline mutation.
- Autosave, LLM/provider/model transport, AgentRun, Worker, Runtime, billing,
  OpenCut/Phase 10 changes, or a second timeline/proposal model.
- Changes to production lineage, Shot/Asset/ProductionGraph/NodeRun/Artifact,
  ProviderOperation, or existing manual editor behavior.

## Owned paths

- `frontend/src/features/editing/api.ts`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/tests/unit/EditingWorkspace.test.tsx`
- `frontend/src/styles/index.css`
- `docs/plans/professional-program-v2/task-contracts/P9-04D-EDITING-DIRECTOR-SUGGESTION-UI.md`

## Verification gate

- Focused EditingWorkspace unit tests and existing editing regressions pass.
- `npm run typecheck`, `npm run lint`, `npm run api:check`, `npm run build`, and
  `git diff --check` pass (or any pre-existing gate issue is reported with evidence).
- No backend, schema, migration, provider, timeline-apply, branch, commit, or push
  is part of this task.
