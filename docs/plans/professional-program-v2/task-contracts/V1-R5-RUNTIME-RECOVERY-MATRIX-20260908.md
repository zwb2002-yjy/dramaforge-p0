# V1 R5 — Production recovery and retry matrix

**Task:** `v1-r5-runtime-recovery-matrix-20260908`\
**Parent:** G7E / Runtime / R4\
**Status:** IN PROGRESS\
**Baseline:** `dev@8d17a67`

## Authority and current evidence

The 2026-09-07 Owner revision requires proof by failure class rather than a
generic automatic retry count. The canonical NodeRun / ProviderOperation /
Artifact path, frozen ExecutionIdentity and Worker recovery already cover much
of the matrix: durable queue failure, remote-id polling recovery,
unknown-submission fail-stop, Retry-After ARQ deferral, dependency gates,
latest-attempt UI projection, command idempotency and invalid-media validation.

Audit found one material runtime gap. `cancel_generation` only writes
`cancel_requested`; queued work is then stranded, an in-flight Worker can later
overwrite that request with `completed`, and restart recovery only selects
`running` rows. Thus the required late remote success cannot be represented as
`completed_after_cancel`, and cancelled remote tasks are not terminally closed.
The Worker also collapses invalid/missing media into generic `WORKER_ERROR`
despite the typed product-path prefix.

## Outcome

- Make pre-submit cancellation terminal without a Provider call. For a
  submitted remote operation, persist cancellation intent, request remote
  cancellation at most once when supported by the runtime, continue observing
  the same remote identity, and record either `cancelled` or
  `completed_after_cancel`. Never promote a late result to Formal.
- Include `cancel_requested` remote tasks in RLS-safe restart recovery and
  preserve cancellation intent while requeueing for observation. Recovery
  never performs another create POST or resolves a new model/binding.
- Preserve provider/media failure classes at the Worker boundary so invalid or
  missing downloads create no available Artifact and remain diagnosable.
- Assemble a focused, machine-readable matrix whose assertions include local
  and remote statuses, create/poll/cancel call counts, frozen identity, Artifact
  hash/lineage and zero-write/zero-provider deltas where required.

## Owned paths

- `backend/app/providers/generation_service.py`
- `backend/app/execution/product_path.py`
- `backend/app/runtime/scheduler.py`
- `backend/app/workers/jobs.py`
- `backend/app/shared/db.py` and `backend/app/shared/errors.py`
- `backend/app/api/v1/generations.py` (CSRF/state projection if required)
- `backend/alembic/versions/20260908_0060_cancel_recovery.py` (new)
- focused unit and real PostgreSQL recovery-matrix tests
- migration-head assertions, this contract and V1 Goal status

## Non-scope and authorization

No blanket catch/retry loop, new execution truth, automatic user redo, Provider
fallback, production data mutation, paid Provider call, global install or Owner
merge. R6 owns final SRT and frozen Timeline render details. R7 owns at least
one real configured remote task and the cross-provider Golden.

## Required matrix / acceptance

1. Redis failure returns `QUEUE_UNAVAILABLE` and the committed NodeRun is failed,
   never a false queued success.
2. Restart with a remote id polls the same id with zero additional create calls;
   submission-started/transport ambiguity without an id becomes
   `unknown_submission` and is never automatically posted again.
3. A classified 429 records the rejected attempt, raises ARQ Retry with the
   supplied delay and reuses the frozen identity on the next allowed submit.
4. Required upstream pending defers; missing/failed/unavailable upstream fails
   before Provider execution. A newer successful attempt is projected while
   older failures remain in history.
5. Same key/same request restores one receipt; changed request conflicts. An
   explicit new key creates the next attempt with parent lineage.
6. Invalid MIME/magic/length/download produces no available Artifact and a
   typed error. A valid result records content hash and `produced_by_run_id`.
7. Queued cancellation performs zero create/cancel calls. Submitted cancellation
   survives restart, calls remote cancel at most once, and terminally records
   cancelled or late-success `completed_after_cancel`; Formal remains unchanged.
8. Focused unit/PostgreSQL, migration upgrade/drift, full backend and relevant
   frontend attempt-projection regressions pass on the committed candidate.
   Evidence reports all four required dimensions, not only test counts.

## Implemented recovery semantics and development evidence

- Queued, never-submitted cancellation is terminal and idempotent with no remote
  call. A recovery-queued run that already has a submission marker/remote id
  retains cancel_requested; a duplicate Cancel API cannot erase remote truth.
- Remote cancellation is atomically claimed once on ProviderOperation, committed
  before I/O. A lost cancel acknowledgement resumes by polling, not repeating
  create/cancel. Concurrent consumers are covered on real PostgreSQL.
- A terminal successful poll wins over a subsequent cancellation acknowledgement.
  Final import serializes against the NodeRun cancellation flag and writes
  completed_after_cancel with adopted_after_cancel=false. No latest-successful
  pointer, Formal selection or downstream auto-adoption is performed.
- The RLS recovery function includes cancel-requested runs/operations and expired
  submission_started rows without remote identity. Fresh markers are left alone
  because another worker may still be live; after the existing 30-minute heavy
  job bound, recovery records unknown_submission/failure without enqueue/create.
  The latest operation is locked and re-read before making a recovery decision.
- Worker results preserve terminal cancellation/late-success and media failure
  classes. Unsupported raw string media, malformed/truncated content, missing
  media, and download transport failures cannot become available Artifacts.
  Remote transport error text is not copied into the typed download reason.
- API cancellation validates CSRF/project scope and materializes its response
  before commit while PostgreSQL RLS context is active.
- Development matrix: 18 real-PG cases report local/remote states, call counts,
  frozen request/binding identity, and Artifact hash/lineage or zero-artifact
  evidence in `tmp/r5-quality-contract/recovery-matrix.json` and `matrix.xml`.
  Cases cover 429 Retry(7s), unknown submission, Redis outage, required dependency
  pending/missing/failed/unavailable/late-unadopted/newer-success, queued cancel,
  remote cancel, late success, lost cancel ack, concurrent cancel, and invalid/
  missing/raw/download-failed media. The control plugin performs no paid call.
- Current focused run: 50 tests PASS. Earlier full precheck: backend unit 978 and
  PG integration 40 PASS; subsequent added download/length cases require the
  final committed-candidate rerun, not an inflated precheck completion claim.
- Existing R4c2 command receipt/idempotency tests and SceneWorkspace attempt
  projection regressions remain mandatory. Timeline/subtitle rerender zero-media
  delta is revalidated with R6; R7 still owes a real configured remote task.
- Original failed fixture runs remain evidence. PostgreSQL enum/edge requirements
  were corrected in the new fixtures rather than weakening schema constraints.
  The old ledger rejects preserved root inputs; no lifecycle event is forged.
