# V1-D3-DIRECTOR-INVOCATIONS-20260910

Status: IN_PROGRESS, local implementation only.

Authority: Owner implementation §7 and Owner design director invocation/runtime
boundaries, registered in the seven-plan README. D1 contracts are implemented
locally; D2 formal closure remains outstanding. Owner sequence permits D3 after
the shared contract boundary, independently of D2. Work remains serial.

Current evidence: DirectorTextTransport creates/claims/commits DirectorTurn,
resolves a profile binding, dispatches through CapabilityRouter, performs one
schema repair, and aggregates evidence on the turn. Primary and repair requests
share the same turn request identity; there is no per-invocation persisted row.
The normalized text request/context/result are already ORM-free and reusable.

Outcome: separate a session-free TextModelPort, context construction and durable
InvocationService from runtime lifecycle. Preserve profile/slot resolution,
actual model identity, output schema, unknown costs and at-most-one repair.
Persist a stable invocation identity before submission; validated completed
results are replayed, while uncertain submitted requests are not blindly retried.
Each repair is separately identified and audited. Production remains unchanged.

Owned paths: director text transport, context/invocation/text-model modules,
neutral text contracts as needed, additive invocation migration/model registry,
related unit/PG/integration tests, and this contract. Runtime engine activation,
UI redesign and new model catalogs are outside D3. No paid calls or changes to
shared runtime databases are authorized by this contract.

Verification: existing text entrypoint tests for binding/usage/error/stale/repair;
session-free dispatch and model identity; real PG invocation uniqueness, RLS,
submission recovery and validated output reuse; bounded repair accounting;
typing/lint and affected API schema compatibility. Mock transport proves control
flow only. Required configured-channel integration and formal lifecycle evidence
must be separately reported; local green checks do not complete D3 or D0-D8.

First slice: extract the network port without changing request identity or
legacy lifecycle. Subsequent slices add the invocation journal and move call
coordination; do not present this first extraction as full separation.

## Incremental evidence

TextModelPort and CapabilityTextModel now accept only existing ORM-free request,
resolved model ID and ExecutionContext; they have no Session, Turn or commit.
DirectorTextTransport delegates dispatch to the injectable port and retains its
legacy lifecycle pending invocation/runtime migration. No alternate model catalog
or provider retry was introduced. Eleven text transport tests pass, including a
session-free real adapter/mock HTTP timeout test asserting SUBMIT_UNKNOWN with
one request. Focused typing and Ruff pass. These tests are not live model quality
or invocation-journal recovery evidence; the journal is still unimplemented.

Expanded entrypoint regression passes 74 tests across shot suggestions,
recommendations, story generation/proposals, editing text and the LiteLLM bridge.
Evidence: `tmp/v1-d1-20260909/d3-text-entrypoints.xml`. This validates the existing
request/output behavior through the extracted port, not D3 completion. No new
database migration, framework dependency or live model request in this slice.

Invocation journal foundation: migration 0064 creates director_invocations with
project RLS, a composite turn/project foreign key, stable turn/invocation-key
uniqueness, positive attempts, status/output consistency and unknown/reported
cost consistency. Nullable validated JSON uses SQL NULL explicitly. Turn gains
the supporting (id, project_id) unique constraint; no existing rows rewritten.
InvocationService serializes preparation on the scoped parent, rejects changed
input under the same identity, reserves submission once, preserves unknown
submission, validates output against the frozen schema and restores completed
evidence without overwrite. The caller still owns transaction commit ordering.

Real app-role PostgreSQL test passes (`d3-invocations-pg.xml`): concurrent prepare
converges, concurrent start has one winner, unknown cannot restart, fresh-session
completed output is retained, conflicting output is rejected, RLS blocks reads
and writes from another project, composite FK blocks forged parent scope, and
database checks reject completed-output/state mismatch and reported-without-cost.
This verifies journal operations, not network-call integration or process-kill
recovery. The journal is not yet used by DirectorTextTransport. Failure evidence,
provider identity/usage mapping, bounded repair wiring and Runtime replay remain.

Focused typing/Ruff pass; 29 legacy text/turn tests pass. Existing migration
upgrade/downgrade/re-upgrade test also passes against head 0064 in an isolated
test database (`d3-migration.log`). No shared database migration or paid model
call occurred. D3 and the overall goal remain incomplete.

## Integrated invocation slice

The earlier journal-foundation notes above are chronological. The current local
implementation now wires DirectorTextRuntimeAdapter to InvocationService and the
session-free TextModelPort. ContextBuilder produces an ORM-free detached JSON
snapshot of versions, intent and effective facts. The legacy
DirectorTextTransport name is a compatibility alias for the transitional runtime
adapter; the actual model transport is TextModelPort and never receives or
commits a business Session.

Primary and schema-repair calls use separate stable invocation keys. Preparation
and submission reservation commit atomically before network I/O. Each request is
bound to the frozen model resolution, request, output schema and intent hash.
Validated results, usage, reported/unknown cost and allowlisted Provider identity
are durable before the Turn summary is advanced. A completed invocation can
rebuild an interrupted Turn without a second model call. A persisted
submission_started record is conservatively changed to unknown_submission on
recovery and is never resent; a Turn that stopped before any invocation row was
committed remains safe to rebuild. Typed pre-submission configuration failures
remain known failures, while an untyped thrown transport outcome is unknown.

Current evidence: 13 context/text unit tests pass; 38 wider text/turn/story tests
pass (`d3-journal-regression.xml`); two real app-role PostgreSQL tests pass
(`d3-transport-recovery-pg.xml`). The PG tests cover concurrent identity,
single-winner submission reservation, RLS/FK/check constraints, completed result
recovery with zero model calls, and uncertain recovery with zero model calls.
The migration head also passes downgrade to 0060 and re-upgrade
(`d3-migration-roundtrip.xml`). Focused Ruff and mypy pass. No live configured
model channel, paid request, shared database migration, D4 engine validation or
formal lifecycle evidence has run, so D3 and the overall goal remain IN_PROGRESS.

## Final local convergence

D5/D6 route new bound Turns through this journal-backed adapter. Current tests
cover verified output persistence, session replacement, separate repair
identity, unknown-submission fail-stop behavior, usage/cost provenance and
zero-resubmit recovery in the actual executor path. The current full Docker
Gate passes. A paid configured-channel invocation remains a D8 candidate
acceptance item; it is not an unimplemented D3 transport boundary.
