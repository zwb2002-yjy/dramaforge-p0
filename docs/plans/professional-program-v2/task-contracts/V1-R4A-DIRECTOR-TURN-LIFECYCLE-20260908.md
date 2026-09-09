# V1 R4a — Durable Director turn lifecycle and recovery

**Task:** `v1-r4a-director-turn-lifecycle-20260908`\
**Parent:** G3 / G4 / G6 / R2\
**Status:** COMPLETE\
**Baseline:** `dev@1f4de4f762427bb9baa94741b895ec639b7b10a1`

## Current evidence and drift

- R2 created the complete `DirectorTurn` table and persists real text-call
  identity, context/output hashes, one bounded schema repair and proposal links.
- Each R2 service currently owns ad-hoc status updates. There is no shared
  revision-checked lifecycle service, atomic queued-turn claim, user stop/read
  API, deadline/step guard, or interrupted-turn recovery policy.
- A process interruption after `submission_started` can leave a turn in
  `thinking`. Text requests do not have a pollable remote task identity, so this
  state must fail visibly as an unknown submission and must never be replayed
  automatically.
- The existing unique `(project_id, request_key)` constraint, status/revision,
  deadline, step count, proposal/command and NodeRun reference fields are enough
  for R4a. The only migration addition is the narrow security-definer resolver
  needed for a Worker to discover recoverable turns without bypassing RLS.

## Outcome

- Add one `DirectorTurnService` as the only new lifecycle authority for creating
  or restoring coordination turns, atomic claim, revision-checked transitions,
  stop/stale handling and bounded interrupted-turn recovery.
- Expose owner-scoped typed read/list/stop endpoints. Reads and recovery never
  invoke a text or media Provider and never create a NodeRun.
- Mark active Shot-scoped turns stale in the same transaction when a user saves
  a newer Shot design, without changing accepted/rejected proposal history.
- Preserve R2 text behavior and evidence while routing its terminal state
  helpers through lifecycle invariants where appropriate.

## Owned paths

- `backend/app/director/turn_service.py` (new)
- `backend/app/director/turn_models.py` only if an invariant needs clarification
- `backend/app/director/text_transport.py`
- `backend/app/api/v1/director.py`
- `backend/app/workbench/shot_service.py`
- `backend/app/shared/db.py`
- `backend/app/workers/jobs.py` and `backend/app/workers/default.py`
- `backend/alembic/versions/20260908_0057_director_turn_recovery.py` (new)
- focused lifecycle/API/concurrency/PostgreSQL tests
- generated OpenAPI types and minimal Director UI reads only if required
- this contract and Goal status

## Out of scope

- R4b event-driven next-action decisions and awaiting-execution reconciliation
- R4c AUTO authorization/media dispatch and complete mode UI
- a generic arbitrary tool executor, a second production graph, automatic
  Candidate→Formal, autonomous aesthetic review or any paid Provider call

## Invariants

- `DirectorTurn` remains coordination/evidence only; NodeRun, ProviderOperation,
  Artifact, Proposal and Canonical Scene/Shot/EditSession facts are referenced,
  never copied as a second execution truth.
- Same request key plus same context returns the existing turn. Same key plus a
  different context conflicts. Claim and transition use revision/status compare
  and swap so only one concurrent worker advances a turn.
- Step/deadline exhaustion yields a readable terminal reason. A text submission
  of unknown outcome fails closed and requires an explicit new request key; it
  is never automatically submitted again.
- Stop prevents new Director actions but does not claim to cancel an already
  submitted media Provider task. Read/list endpoints are side-effect free and
  project/workspace/owner scoped.

## Acceptance

1. Duplicate create and concurrent claim return one turn and one successful
   claim; a changed context under the same request key conflicts.
2. Revision mismatch, illegal transition, cross-project read/stop and expired or
   step-exhausted work fail closed with typed reasons.
3. Interrupted `thinking/submission_started` becomes durable failed/
   `text_submission_unknown`; recovery performs zero text/media calls and a
   second recovery is idempotent.
4. User Shot save marks its active turns stale in the same commit; late R2 model
   output cannot change Canonical Shot design or revive the stale turn.
5. Refresh/re-entry reads status, wait reason, proposal/command/NodeRun links,
   model identity and bounded error without generating new work.
6. Full relevant backend, PostgreSQL and generated API/frontend gates pass.

## Result

- `DirectorTurnService` now owns idempotent create/restore, atomic revision/status
  claim, allow-listed compare-and-set transitions, user stop, scope stale,
  deadline/step bounds and fail-stop interrupted-submission recovery.
- Every R2 structured text entry creates and claims through this lifecycle
  before transport. The durable `submission_started` record is committed before
  external I/O; late model evidence may be retained after a concurrent user
  stop/edit, but cannot revive a cancelled/stale turn or apply its output.
- Owner-scoped typed list/read/stop APIs expose safe context/model/result/linkage
  evidence after refresh. Stop keeps existing NodeRun links intact and explicitly
  does not claim to cancel in-flight media.
- Saving a Shot marks its active Shot-scoped turns stale in the same database
  transaction. Existing optimistic Shot version checks and proposal decisions
  remain authoritative.
- Migration `0057` adds only the RLS-safe recoverable-turn resolver and minimum
  resolver-role read grant. The default Worker startup scan handles expired turns
  and stale unknown text submissions without invoking any Provider or creating a
  NodeRun. PostgreSQL concurrency proves only one Worker can claim a turn.
- Same-candidate checks: Ruff PASS; MyPy `240` source files PASS; backend unit
  `934` PASS; migration upgrade/drift PASS; PostgreSQL integration `22` PASS.
  Generated API check, Prettier, ESLint, native TypeScript 7, frontend unit `145`,
  production build and Playwright `19` PASS. No paid/external Provider call was
  made.

## Next

R4b adds the finite next-action whitelist and idempotent business-event
reconciliation, stopping at the next explicit user confirmation point.
