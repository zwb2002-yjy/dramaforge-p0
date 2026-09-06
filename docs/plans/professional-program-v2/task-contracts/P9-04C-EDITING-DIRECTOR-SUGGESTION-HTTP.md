# Task: P9-04C — Editing Director Suggestion HTTP Bridge

## Status

- **State:** COMPLETE
- **Program order:** P9-04B Editing Director Suggestion → persisted proposal
  → **P9-04C Editing Director Suggestion HTTP Bridge** → later P9-04 UI and
  approved model transport
- **Task id:** `p9-04c-editing-director-suggestion-http`
- **Task boundary:** Expose the existing P9-04B deterministic suggestion
  service through one project/session-scoped HTTP route.  Return the exact
  persisted proposal and item identities together with the validated
  suggestion; do not apply the pending command.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`P9-OPENCUT-EDITING.md`](P9-OPENCUT-EDITING.md) — DramaForge/OpenCut truth
  boundary
- [`P9-04A-EDITING-PROPOSAL-APPLY.md`](P9-04A-EDITING-PROPOSAL-APPLY.md) —
  typed timeline command and optimistic version
- [`P9-04B-EDITING-DIRECTOR-SUGGESTION.md`](P9-04B-EDITING-DIRECTOR-SUGGESTION.md)
  — service, stale gates and deterministic transport
- Existing `backend/app/api/v1/editing.py` and generated frontend API contract

## Current evidence / drift

- P9-04B reads a server-owned `EditSession`, validates a narrow typed plan,
  checks the version before and after transport, and persists one pending
  `DirectorProposalItem` without applying it.
- P9-03A already owns project/session HTTP scoping, selected-workspace
  dependency, ownership checks and CSRF enforcement patterns.
- The service previously returned only the validated candidate, so an HTTP
  caller could not identify the exact rows created by that invocation.

## Implementation contract

1. **Narrow request and server identity.** Add
   `POST /projects/{project_id}/edit-sessions/{session_id}/director-suggestion`.
   The JSON body accepts exactly `expected_session_version` and a non-blank
   `user_instruction`; project and session identity come only from the route.
   Selected-workspace, project ownership, project/session scoping, CSRF and
   both P9-04B stale gates remain mandatory.
2. **Persisted-result identity.** Extend the service result to carry
   `proposal_id`, `item_id`, and the validated candidate.  Both IDs must be
   read from the proposal/item rows flushed in the same invocation; no latest
   proposal/item query, timestamp selection, or identity-map inference is
   allowed.
3. **Proposal-only route.** Return structured `proposal_id`, `item_id`, and
   `suggestion` data.  Delegate all reads, validation, persistence and stale
   handling to `EditingDirectorSuggestionService`; the route contains no SQL
   and never applies a command, edits a timeline, calls a provider, or starts
   execution.
4. **Contract evidence.** Regenerate
   `frontend/src/shared/api/generated.ts` from the FastAPI OpenAPI schema.
   Add focused unit/API coverage for exact IDs, pending command payload and
   expected version, request extra-field rejection, stale/cross-project/
   non-owner/CSRF fail-closed behavior, immutable fact snapshots and the
   deterministic no-network path, while retaining P9-04A/B regressions.

## Explicitly out of scope

- P9-04 UI, accept/reject/partial-apply, automatic apply, autosave, or any
  timeline mutation from this route.
- LLM/model/provider transport, network calls, AgentRun, Worker,
  ProviderOperation, Runtime, billing, OpenCut integration, or Phase 10.
- New tables, migrations, idempotency redesign, JSON Patch, raw SQL, arbitrary
  writes, or changes to proposal/thread schemas.
- Changes to Shot, Asset, formal production lineage, ProductionGraph, NodeRun,
  Artifact, or other production/execution facts.

## Owned paths

- `backend/app/director/editing_suggestion.py`
- `backend/app/api/v1/editing.py`
- `backend/tests/unit/test_editing_director_suggestion.py`
- `backend/tests/unit/test_editing_api.py`
- `frontend/src/shared/api/generated.ts` (generated contract only)
- `docs/plans/professional-program-v2/task-contracts/P9-04C-EDITING-DIRECTOR-SUGGESTION-HTTP.md`

## Verification gate

- Focused P9-04B service tests and P9-04C API tests pass, including exact
  same-invocation IDs, persisted command identity/version, stale-before and
  stale-after zero persistence, ownership/scope/CSRF/extra-field rejection,
  no provider/network dispatch, and unchanged editing/production facts.
- `ruff check app tests`, `mypy app`, frontend `npm run api:check`, and
  `git diff --check` pass.  No branch, commit, push, migration, or provider
  operation is part of this task.
