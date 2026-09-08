# V1 R4c1 — Durable user decisions and autonomy intervention

**Task:** `v1-r4c1-director-user-decisions-20260908`\
**Parent:** G3 / G4 / G6 / R4c\
**Status:** IMPLEMENTED / VERIFIED (formal ledger registration unresolved)\
**Baseline:** `dev@773febf`

## Authority and current drift

The registered 2026-09-07 Owner revision, implementation §8 R4c, requires user
intervention to win, rejection to close the same suggestion branch, and MANUAL
to stop new automatic actions without pretending to cancel submitted media.
The original seven-plan product user/Proposal-first and canonical boundaries
remain unchanged (01 §§4–6, 02 Director Assistant, 06 review overrides).

R4a invalidates active Shot turns on user design save. R4b can reconcile typed
proposal decisions and actual NodeRun states, but detached Shot text suggestions
still have no durable item decision. A new request key can regenerate a rejected
unchanged context. Creative-profile changes version the profile but leave old
Director turns active. These are the bounded gaps addressed here.

## Outcome

- Persist explicit whole/partial acceptance or rejection for detached typed text
  suggestions, with revision checks, valid operation indices and immutable
  decision replay. Decisions never apply Canonical content or dispatch media.
- Reject regeneration of the same rejected context before text transport and
  before creating another turn; a genuinely changed context remains eligible.
- Changing autonomy invalidates active coordination turns in the same transaction
  as the profile revision. Existing NodeRun/ProviderOperation state is untouched.
- Keep MANUAL explicit user suggestions available; do not relax the existing
  proactive recommendation suppression or any execution identity.

## Owned paths

- `backend/app/director/turn_service.py`
- `backend/app/director/next_action.py` (preserve accepted draft checkpoint on resume)
- `backend/app/director/text_transport.py`
- `backend/app/api/v1/director.py`
- `backend/app/api/v1/projects.py`
- focused Director user-decision / API / PostgreSQL tests
- `frontend/src/shared/api/generated.ts`
- this contract, the V1 Goal status, and the R4b contract evidence-only closeout

## Non-scope

- Media dispatch, automatic Formal selection, auto-save or generic tool execution.
- Runtime/Provider changes or a new production truth.
- R4c2 Workbench command linkage / Formal and EditSession checkpoints.
- R4c3 refresh-safe Director UI and explicit decision controls.
- Global installs, paid Provider calls, production mutation, and Owner merge.

## Acceptance and verification

1. Whole/partial/reject decisions survive separate sessions; duplicate exact
   decisions are read-only, conflicting decisions/version or cross-project fail.
2. Invalid/out-of-range/repeated operation indices and attempts to use this API
   on canonical DirectorProposal rows fail closed. No Canonical or media changes.
3. Rejected context under another request key produces zero new turns or text
   calls; changed Shot/instruction/context can create an explicitly requested turn.
4. Autonomy change makes active turns stale, preserves rejection history and
   submitted NodeRuns; late text output cannot revive stale turns.
5. Focused unit/API/real PostgreSQL checks, full relevant backend/static tests,
   generated API/frontend type checks pass. No mock evidence is called Golden.
6. Commit and review the scoped diff; preserve the known root-ledger recovery
   limitation without forging formal completion. Final R7/R8 gates remain due.

## Implementation notes

- Detached Shot suggestions/recommendations expose a strict, CSRF/owner-scoped
  decision API. Whole/partial acceptance records only valid operation indices,
  re-reads/locks current Shot versions, and still requires an explicit design
  save. Linked canonical proposals and production confirmations cannot use it.
- Exact decision replay is immutable and revision-safe. Rejection closes the
  branch and invalidates already-created active sibling requests with the same
  context; the text-result handoff checks the rejection guard again.
- Mode updates version the CreativeProfile and invalidate active project turns
  transactionally. Rejected history and existing NodeRun states are untouched.
- A new reload test exposed SQLAlchemy's Python-side UPDATE synchronization
  comparing SQLite's offset-naive loaded deadline with an aware current time.
  Claim and CAS now let the database evaluate the deadline predicate, then use
  their existing explicit refresh. No deadline/step guard was relaxed.
- Canonical Shot locks populate existing ORM rows, so an earlier identity-map
  snapshot cannot defeat acceptance's current-version check.
- Verification uses the pinned R4b quality runtime with current scoped source
  mounted explicitly. It is task development evidence, not an immutable R8
  release image or real paid-provider Golden.
- The known root-ledger registration restriction remains unresolved; no
  STARTED/COMPLETED event was forged and the two Owner input files stay in place.

## Following R4c work

R4c2 must link actual Workbench commands/receipts and Formal/EditSession business
checkpoints, and cover authorization/context races before dispatch. R4c3 must
rehydrate the UI, submit these explicit decisions and treat a returned stale or
cancelled turn as non-applicable. This subtask does not claim those behaviors.

## Verification result

Final scoped source passed Ruff, MyPy (241 app files), all 965 backend unit
cases, and all 22 PostgreSQL integration cases. Migration remains `0058` and
upgrade/drift checks passed without a schema change. Generated API consistency,
Prettier, ESLint and native TypeScript checks passed. Full backend results are
`tmp/r4c1-quality-contract/backend-final.log`; frontend contract results are
`tmp/r4c1-quality-contract/frontend-contract.log`. No real paid Provider request
or production write was made. R4c UI and real command linkage are still pending.

The R4c3 review must also preserve the frozen preview-to-dispatch identity and
expose exact/approximate/unsupported delivery with explicit approximation
confirmation, as required by the Owner's R3/R4 revision; do not silently accept
an execution preview merely because a previous task was marked complete.
