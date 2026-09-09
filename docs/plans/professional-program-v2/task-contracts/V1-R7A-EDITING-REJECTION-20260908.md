# V1 R7a — Close the persisted Editing rejection branch

**Task:** `v1-r7a-editing-rejection-20260908`\
**Parent:** R7 real acceptance / R4 user intervention\
**Status:** IMPLEMENTED / FOCUSED VERIFIED (formal ledger registration unresolved)

## Evidence and authority

Owner revision §8 R4c requires rejected suggestions to end their branch across
refresh, with no rephrased/regenerated request absent changed context. R7 §11
requires real Editing user decisions. Inspection before paid acceptance found
EditingWorkspace.rejectSuggestion only clears browser state. The real suggestion
already has DirectorProposal/Item/Turn ids, but no Editing-scoped rejection API
is wired. Thus the R4 completion statement did not cover this actual UI path.

## Outcome and owned paths

- Add a CSRF/owner/project/EditSession/version-scoped typed rejection endpoint in
  `backend/app/api/v1/editing.py`. Reuse ProposalService and the existing business
  reconciler; never apply a timeline or create a Provider/NodeRun.
- Wire `frontend/src/features/editing/api.ts` and `EditingWorkspace.tsx` so success
  clears preview only after persistence; failed/late requests cannot silently
  discard the preview or affect another session. Lock conflicting preview actions
  while rejection is pending.
- Focused backend API/PG and frontend rejection/race tests, generated OpenAPI,
  this contract and Goal status. Whole/partial apply-to-draft + explicit Save stays
  unchanged; this fix does not introduce server auto-apply or a second timeline.

## Acceptance

1. Rejection persists canonical item status and completes the associated turn;
   replay is idempotent, and unchanged-context generation is rejected before text.
2. Cross-project/session, stale version, already accepted items, malformed body
   and missing CSRF fail closed; no timeline/version/Formal/media mutations.
3. UI retains preview after rejection error, reports success only on server ack,
   and ignores a late result after route/session change.
4. Required focused/static/generated frontend and real PostgreSQL tests pass.
   No paid calls are needed for this defect fix. R7 actual Golden remains due.

## Result

The new rejection endpoint reuses canonical ProposalService and the persisted
Director reconciler. Items become rejected and linked turns completed in the same
transaction, with no Timeline/NodeRun/Provider mutation. Repeat acknowledgements
are read-only; invalid scope, stale base version, unknown fields and CSRF fail.
The UI waits for a matching server acknowledgement, retains preview after errors,
disables conflicting actions while pending and ignores stale acknowledgements.
Focused backend/driver/PG 11 tests PASS; MyPy 243 files and Ruff PASS; Editing UI
30 tests PASS, including failure and late-version response handling. Generated
API/types were regenerated and frontend typecheck/lint passed. No paid call.
Evidence: `tmp/r7a-quality-contract/pg-rejection.log`,
`rejection-race-ui-rerun.log` and `frontend-focused.log`.
