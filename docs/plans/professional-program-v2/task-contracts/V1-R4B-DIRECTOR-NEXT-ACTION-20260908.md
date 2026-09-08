# V1 R4b — Finite Director next-action reconciliation

**Task:** `v1-r4b-director-next-action-20260908`\
**Parent:** G3 / G4 / G6 / R4a\
**Status:** IMPLEMENTED / VERIFIED (formal ledger registration unresolved)\
**Baseline:** `dev@eaff325532fae780f521737fe2fac4648443ff4a`

## Current evidence and drift

- R4a now has durable turns, revision-safe state changes, stop/stale behavior and
  fail-stop restart recovery. It intentionally does not decide what comes next.
- `awaiting_execution`, proposal links, command keys and NodeRun ids exist but no
  service re-reads those facts and advances to a typed confirmation point.
- Browser-independent media recovery exists for NodeRuns. There is no low-rate
  Director scan that observes their terminal state and updates the associated
  turn, so a closed browser cannot surface the next Director checkpoint.
- The autonomy enum exists, but AUTO and ASSIST still project the same
  post-production behavior. MANUAL suppression is deferred to R4c's user-mode
  intervention wiring.

## Outcome

- Add a strict finite next-action vocabulary and one reconciliation service that
  derives actions only from current Proposal/NodeRun/ProjectCreativeProfile
  facts. It never trusts an event payload as business truth.
- Deduplicate each business fact-set on the turn under revision compare-and-set;
  one changed fact-set consumes at most one bounded step, while repeated scans
  are read-only.
- Reconcile `awaiting_execution` to in-progress, failure review, or the next
  explicit Formal confirmation point. AUTO reads through to that checkpoint;
  ASSIST recommends review; neither promotes Formal or dispatches another paid
  command.
- Add a low-frequency Worker scan and an owner-scoped explicit resume endpoint.
  Both are safe after browser closure and create no Provider call or NodeRun.

## Owned paths

- `backend/app/director/next_action.py` (new)
- `backend/app/director/turn_service.py`
- `backend/app/api/v1/director.py`
- `backend/app/shared/db.py`
- `backend/app/workers/jobs.py` and `backend/app/workers/default.py`
- `backend/alembic/versions/20260908_0058_director_waiting_turns.py` (new)
- focused next-action/API/Worker/PostgreSQL tests
- `backend/app/director/text_transport.py` (bounded turn step budget)
- generated OpenAPI types
- this contract and Goal status

## Out of scope

- Automatically applying proposals or saving browser drafts
- Automatically dispatching paid media, selecting Candidate→Formal, exporting a
  film, or making another text-model request
- R4c mode-change cancellation, user-linked save/decision commands and complete
  Director status UI

## Invariants

- Allowed actions are a typed enum, never an arbitrary tool/command/path.
- Proposal, Shot, NodeRun and Profile rows remain canonical. Reconciliation may
  only update DirectorTurn coordination fields after re-reading those rows.
- Same fact-set/event under duplicate API, cron or Worker delivery changes the
  turn at most once. Revision races resolve by reading the winner.
- Step/deadline bounds stop advancement with a readable reason. No scan extends
  authorization or silently retries text/media submission.
- Formal selection and all paid actions remain explicit existing business gates.

## Acceptance

1. Duplicate reconciliation and two concurrent consumers record one event and
   one step; a changed NodeRun terminal state records one new decision.
2. Active execution stays waiting; failed execution yields visible failure
   review; successful execution reaches an explicit Formal confirmation point.
3. AUTO and ASSIST have distinct typed post-production actions; neither creates
   a NodeRun/ProviderOperation or changes Shot Formal ids.
4. A rejected proposal ends that branch and the same unchanged facts cannot
   regenerate/rephrase it. Partial acceptance reports only accepted items.
5. Worker restart/periodic scan and explicit resume re-read persisted state, are
   idempotent, and work after browser closure.
6. Cross-project, illegal state, missing link, deadline and step exhaustion fail
   closed. Full relevant backend/PostgreSQL/generated frontend gates pass.


## Recovery and validation record (2026-09-08)

- Resumed the original interrupted Goal at `eaff325`, preserving all R4b changes
  and both untracked Owner-supplied root documents. No paid Provider call,
  production mutation, service replacement, or cross-task cleanup is authorized
  by this subtask.
- Added stable terminal-checkpoint replay, duplicate-event race recovery across
  distinct event keys, fail-closed unknown proposal states, explicit stale-proposal
  handling, and committed finite-limit failures in both API and Worker callers.
- Recovery scanning uses bounded UUID keyset pages so unchanged/invalid early
  rows do not starve later turns; the Worker context tracks only its scan cursor,
  never business execution state. Process restart safely begins another sweep.
- Focused checks: Ruff and MyPy (241 source files), 21 focused unit tests, and
  two real PostgreSQL integration tests passed. The PG race synchronizes both
  consumers before compare-and-set, with distinct keys proving one step/event.
- A first OpenAPI export invocation lacked test-only Settings; after supplying
  the repository quality configuration, export was rerun. This is harness setup,
  not a product model fallback or a passing full gate.
- Ledger STARTED could not be appended: the existing control script rejects the
  preserved dirty root checkout (`repository root dev worktree must stay clean`).
  No event was forged, user input hidden, or history rewritten. Formal ledger
  completion is not claimed; full same-candidate validation is still pending.

### Full mounted-source precheck

- Backend unit: 948 passed. PostgreSQL upgrade to `20260908_0058`, Alembic
  drift check, and all 22 PostgreSQL integration tests passed.
- Generated API consistency, Prettier, ESLint, native TypeScript, frontend unit
  (145), production build, and Playwright (19) passed. Existing non-failing
  Starlette deprecation and one frontend mock-query warning remain visible.
- A final scan-cursor correction shares a nested startup-initialized dictionary
  across ARQ's shallow per-job context copies. Its regression passes fresh copies
  of the context, rather than incorrectly assuming one mutable top-level object.
- These results are development prechecks, not R7 real Provider Golden or R8
  Release Candidate evidence. Final immutable-source checks follow the commit.

- Final focused replay precheck: 22 unit tests passed, including read-only replay
  of the last allowed step. Only a new decision consumes the step budget; an
  expired deadline still stops a repeated scan. The first source commit is
  `ac521d2`; a trailing blank line identified by diff-check is removed before
  the immutable-source candidate is assembled.

## Immutable-source result

`773febf` passed the clean-worktree Docker gates and was pushed to `origin/dev`.
Ruff, MyPy (241 files), 949 backend unit tests, migration upgrade/drift, 22 PG
integration tests, generated API, frontend static/build, 145 frontend unit tests
and 19 Playwright tests passed. Image identities and exact-source facts are in
`tmp/r4b-quality-contract/result-773febf.json`; corresponding complete logs are
`backend-773febf.log` and `frontend-773febf.log` in that directory. No real paid
Provider was called. R4c code work can proceed; this does not claim the blocked
ledger event, R7 Golden, or R8 release gate complete.
