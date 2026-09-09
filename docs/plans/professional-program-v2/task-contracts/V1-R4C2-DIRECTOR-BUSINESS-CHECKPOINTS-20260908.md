# V1 R4c2 — Actual Workbench commands and business checkpoints

**Task:** `v1-r4c2-director-business-checkpoints-20260908`\
**Parent:** G3 / G4 / G6 / R4 / R5 recovery proof\
**Status:** IMPLEMENTED / VERIFIED (formal ledger registration unresolved)\
**Baseline:** `dev@78a4350`

## Authority and drift

The registered Owner revision (2026-09-07, implementation §8 R4b/R4c) requires
actual proposal/save/Formal/production/EditSession business points, idempotent
receipt recovery and authorization-aware continuation. Canonical Project/Shot,
NodeRun, ProviderOperation and Artifact remain the sole business/runtime facts.
The seven-plan source order and 06 frozen-identity/no-fallback rules still apply.

R4b's tests seed awaiting_execution turns, but the actual Workbench path does
not create or associate them. Workbench creates a NodeRun with a unique command
key but does not restore an existing receipt or allocate a new per-node attempt;
thus a lost HTTP response/repeated POST can hit uniqueness errors rather than
returning the committed frozen result. Formal selection and timeline saves do
not notify coordination, and waiting-result turns are excluded from later scans.
Inspection also confirmed that proactive Shot/Editing services had no server-side
MANUAL gate; UI policy alone was not sufficient authorization.

## Outcome

1. Restore a Workbench command's existing NodeRun before model/plan resolution,
   using its frozen request identity. Same key + changed request conflicts; a
   duplicate never creates another graph/run/upstream or reroutes a model.
   A scoped read-only receipt endpoint supports lost-response inspection.
2. New explicit commands allocate the next serialized attempt on the same
   canonical graph node, with prior-attempt lineage. No new runtime/retry loop.
3. Actual AUTO/ASSIST Workbench dispatch records one bounded follow-up turn in
   the same transaction as the NodeRun. MANUAL creates no proactive follow-up;
   mode changes cannot revive a prior cancelled/stale turn. This does not grant
   another paid command or bypass preview/Save/Formal gates.
4. Reconciliation re-reads Shot Formal facts and actual linked NodeRuns. AUTO
   exposes the next stage/Editing confirmation point; ASSIST remains advisory.
   Explicit Formal selection closes that bounded stage and never auto-promotes
   candidates or dispatches more media.
5. Proposal decisions and manual EditSession saves notify/invalidate associated
   turns transactionally. A bounded recovery scan covers waiting Formal facts,
   so missed callbacks/browser closure cannot require an automatic resubmit.
6. Cover context/autonomy races at new proactive text requests and result handoff;
   explicit MANUAL requests remain available. Frozen paid execution identity is
   never re-resolved by reads/recovery.

## Owned paths

- `backend/app/director/business_checkpoints.py` (new)
- `backend/app/director/next_action.py`, `turn_service.py`, `text_transport.py`
- `backend/app/director/recommendation.py`, `editing_suggestion.py` if needed for
  actual proactive-request authorization snapshots
- `backend/app/director/proposal_service.py`
- `backend/app/production/workbench_execution.py`
- `backend/app/api/v1/workbench.py`, `editing.py`, `director.py`, `projects.py` as needed
- `backend/app/shared/db.py`
- `backend/alembic/versions/20260908_0059_director_formal_checkpoints.py` (new)
- focused Workbench/Director/API/PostgreSQL tests and migration-head assertions
- generated OpenAPI types, this contract and Goal status

## Non-scope and authorization

No automatic paid media/text step, Provider retry, model fallback, Final Film
export, timeline auto-save, migration of historical media or second execution
truth. No production write, global install, paid-provider call or Owner merge.
The previous quality PostgreSQL namespace may be reused for isolated tests;
other sessions, Owner files and historical evidence remain untouched.

## Acceptance / verification

- Duplicate and concurrent command calls return one NodeRun/turn and one frozen
  request identity; changed-payload key reuse fails before mutation.
- Receipt read/replay after profile or Shot changes returns the original frozen
  model/result and never calls resolution/provider. A new request still passes
  every current preview/version/reference/approximation gate.
- Two explicit distinct commands on one graph node produce distinct increasing
  attempts, not a uniqueness failure or silent replay.
- Actual API dispatch -> Worker result readback -> explicit Formal confirmation
  reaches the typed next checkpoint, with no extra NodeRun/ProviderOperation.
- Manual/mode-change, stale/stop, cross-project, missing linkage and limits fail
  closed; direct API calls cannot bypass the business confirmation boundaries.
- PostgreSQL concurrency, migration/RLS and recovery tests; full relevant backend
  static/unit/PG regression and generated API/frontend type checks pass.
- Preserve the known ledger-registration restriction rather than fabricate
  STARTED/COMPLETED. Record commit/evidence accurately; R4c3 UI and R7/R8 remain.

## Implementation and verification result

- Workbench receipts bind the validated request hash and frozen plan fingerprint.
  Existing command reads/replays precede mutable Shot/model resolution, including
  after a binding is disabled; changed request/key reuse is a typed conflict.
  Project command locking plus graph-node attempt ordering gives distinct new
  commands monotonic attempts with prior-run lineage. No Director dependency was
  added to the production service or Provider runtime.
- The actual owner-scoped Workbench API creates its AUTO/ASSIST follow-up turn in
  the same transaction as the authorized NodeRun. Its response is materialized
  before commit, while RLS scope is still active. MANUAL dispatch remains usable
  and creates no proactive follow-up. Receipt GET is read-only.
- Formal callbacks and recovery re-read actual Shot/NodeRun/graph scope. Confirmed
  keyframes offer AUTO a video-preview checkpoint; confirmed videos offer Editing.
  ASSIST stays advisory. The completed decision carries the current Shot version;
  no callback creates another media run or automatically selects Formal media.
  Expired coordination cannot roll back a valid explicit Formal selection.
- Proposal decisions are serialized and immutable on replay; stale failures keep
  their readable reason. Rejected items cannot be flipped back or reapplied by
  repeating a decision request. Full and partial rejection block unchanged
  regeneration from detached or canonical proposal facts, without waiting for a
  background scan. Manual timeline saves stale only their scoped Director turns.
- Proactive Shot and Editing services now enforce AUTO/ASSIST on the server and
  freeze the creative-profile authorization version. The profile row lock lasts
  until the text bridge's durable submission boundary, not across external I/O.
  Same-mode profile PATCH is a no-op, not a fresh authorization version.
- PostgreSQL tests run command concurrency as `dramaforge_app`, prove a single
  receipt/turn for two consumers, allocate attempts 1/2/3 for distinct commands,
  and observe an actual `pg_blocking_pids` lock wait during a MANUAL switch.
  The reused controlled fixture was corrected to use an existing credential and
  valid completed-run Artifact lineage, rather than weakening PG constraints.
- Final results: Ruff PASS; MyPy 242 app files PASS; backend unit 977 PASS;
  PostgreSQL integration 23 PASS; upgrade to `20260908_0059` and drift PASS;
  generated API consistency, Prettier, ESLint and native TypeScript PASS.
  Migration tests verify the resolver's definer owner and absence of PUBLIC
  execute permission, including correct handling of default ACLs.
- Evidence: `tmp/r4c2-quality-contract/backend-unit-final.log`,
  `postgres-final.log`, `frontend-contract.log`; earlier failing attempts remain
  development evidence. These use pinned quality runtimes with explicitly
  mounted scoped source, not an R8 immutable release image.
- API business-flow tests use controlled media completion and actual Director
  reconciliation/Formal APIs; they are not real Provider Golden evidence.
  No real paid Provider request, production deployment/write or Owner merge was
  performed. R4c3 UI and the remaining R5–R8 outcomes still require implementation
  and evidence. The preserved-root ledger restriction remains recorded honestly.
