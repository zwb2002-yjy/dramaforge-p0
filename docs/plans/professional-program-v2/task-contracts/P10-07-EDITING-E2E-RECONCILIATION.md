# Task: P10-07 — Editing E2E Contract Reconciliation

## Status

- **State:** COMPLETE
- **Task id:** `p10-07-editing-e2e-reconciliation`
- **Program order:** P10-06 Golden Project（已完成）→ **本 bounded reconciliation** → P10 V1 E2E / Release Gate
- **Task boundary:** 将 `professional-edit.spec.ts` 与共享 professional mock 对齐到当前 P9-03A/B、P9-04A/B/C/D 和 OpenCut manifest v2 契约，形成一条连续的 editing 业务路径。该任务只修正 E2E 证据，不改变生产前后端实现。

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`P10-V1-E2E.md`](P10-V1-E2E.md) — Phase 10 E2E boundary
- [`P9-03A-EDITING-SESSION-HTTP.md`](P9-03A-EDITING-SESSION-HTTP.md) — session HTTP and CSRF
- [`P9-03B-EDITING-WORKSPACE-SESSION-UI.md`](P9-03B-EDITING-WORKSPACE-SESSION-UI.md) — exact route/session UI
- [`P9-04A-EDITING-PROPOSAL-APPLY.md`](P9-04A-EDITING-PROPOSAL-APPLY.md) — versioned typed timeline command
- [`P9-04B-EDITING-DIRECTOR-SUGGESTION.md`](P9-04B-EDITING-DIRECTOR-SUGGESTION.md) — deterministic proposal service
- [`P9-04C-EDITING-DIRECTOR-SUGGESTION-HTTP.md`](P9-04C-EDITING-DIRECTOR-SUGGESTION-HTTP.md) — exact suggestion HTTP bridge
- [`P9-04D-EDITING-DIRECTOR-SUGGESTION-UI.md`](P9-04D-EDITING-DIRECTOR-SUGGESTION-UI.md) — pending preview and isolation

## Current evidence / drift

- The existing editing spec still asserted the removed `editing-api-blocker` and stopped at a read-only manifest shell.
- The current production route returns `opencut-manifest-v2` with the formal video, audio, and subtitle tracks.
- The current UI requires an explicit `POST /projects/{project_id}/edit-sessions`, exact `?sessionId=` navigation, exact session `GET`, explicit editable-timeline `PATCH`, exact-session export, and a versioned proposal-only Director suggestion.
- The previous shared mock returned an obsolete v1 manifest and did not persist editing state across create, save, reopen, and suggestion requests.

## Implementation contract

1. **Formal manifest.** Mock the current `opencut-manifest-v2` response, including the exact adapter identity, formal line, timeline metadata, three tracks, and two formal video clips so local reorder is meaningful.
2. **One persisted editing path.** Start from the formal manifest, create one deterministic EditSession with one CSRF-backed POST, navigate to the exact returned session id, and load only that server-owned session. The mock shares the same session state across all subsequent requests.
3. **Editable save boundary.** Perform a local clip reorder and finite duration edit, then issue exactly one CSRF-backed `PATCH` whose body is only `{timeline: {clips, metadata}}`; reject/record any `production_lineage` payload and increment the mock session version once.
4. **Reopen/export.** Reload the exact `?sessionId=` URL, assert the saved v2 timeline and version, then call the exact session export route and assert the read-only summary without modifying lineage.
5. **Proposal-only suggestion.** Use the reopened session's actual version in one exact project/session POST body containing only `expected_session_version` and `user_instruction`. Return deterministic `proposal_id`, `item_id`, typed reorder/duration operations, rationale, benefit, cost, risk, and impact; assert the UI marks the result `pending`/unapplied and that no timeline or production fact changes.
6. **Request and side-effect evidence.** The shared mock explicitly checks method, path, CSRF, and allow-listed bodies for editing lifecycle calls, retains a request audit, and the spec asserts no provider/runtime/worker/generation dispatch. No obsolete blocker assertion remains.

## Explicitly out of scope

- Production backend/frontend changes, schema or migration changes, provider/model/runtime/worker/generation changes, and OpenCut production behavior changes.
- P10 Golden Project, migration/no-guess audit, RLS/model-resolution audit, UI consolidation, or any Phase 10 task other than this bounded editing E2E reconciliation.
- Updating `docs/reviews/V1-RELEASE-GATE-REPORT.md`, declaring the final V1 Gate, or committing/pushing a branch.

## Owned paths

- `frontend/tests/e2e/professional-edit.spec.ts`
- `frontend/tests/e2e/professional-mocks.ts`
- `docs/plans/professional-program-v2/task-contracts/P10-07-EDITING-E2E-RECONCILIATION.md`

## Verification gate

- Focused `professional-edit.spec.ts` passes with one continuous manifest → create → exact session → local edit → save → reopen → export → current-version suggestion path.
- Full Playwright E2E, frontend Vitest, `typecheck`, `lint`, `api:check`, `build`, and `git diff --check` pass.
- Results are reported as task evidence only; this contract does not update the V1 release report or make a final V1 Gate declaration.
