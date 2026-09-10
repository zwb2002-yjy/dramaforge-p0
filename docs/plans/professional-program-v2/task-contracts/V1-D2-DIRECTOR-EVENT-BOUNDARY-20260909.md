# V1-D2-DIRECTOR-EVENT-BOUNDARY-20260909

Status: IN_PROGRESS, local implementation only.

Authority: registered Owner implementation §6; D1 shared acceptance/read/control
contracts exist and focused functional/PG checks pass. D1 full convergence and
formal lifecycle bookkeeping remain outstanding; no package completion claimed.

Outcome: production commits facts and durable events without synchronously
creating or reconciling director turns. Director independently receives events,
persists deduplication and wakeup intent, and resumes with committed facts.

Owned paths: production application event writer/commands, workbench API,
director business checkpoints and event consumer, events persistence, shared
model registry/DB scoped discovery, required additive migration, worker startup
and queue configuration; relevant unit/PG/Redis tests and this contract.
The remaining ProposalService apply/reject checkpoint hook is included in this
transaction-boundary scope; proposal commands and explicit decision semantics
remain the existing business authority.

Sequence: establish transactional notices and prove replay/rollback behavior;
add persistent Inbox/wakeup and independent consumer; then remove synchronous
workbench checkpoints and prove manual execution when director is stopped.
Do not remove existing followup before its durable replacement is wired.

Current evidence: workbench acceptance and Formal routes invoke director before
commit, receipt read queries DirectorTurn; default worker reconciles existing
turns. EventService already writes EventLog and Outbox in caller transaction;
formal RedisStreamPublisher exists. Reuse these, with independently acknowledged
director delivery rather than treating published as processed.

Required tests: command replay emits no second acceptance, transaction rollback
leaves no notice, duplicate/out-of-order delivery converges, crash before/after
Inbox commit/queue insertion recovers, director failure cannot roll back manual
production/Formal/Export, RLS isolates projects. Real PG/Redis/worker fault tests
are required, not replaced by unit tests. No paid Provider calls for this task.
Formal completion requires reviewed commit and full D2 evidence. Existing user
files and runtime databases remain protected.

## Incremental evidence

Shared acceptance now appends `production.facts.v1` / `execution_accepted` through
the existing EventService in the caller transaction. The PostgreSQL application
test proves duplicate acceptance emits one notice, and rolling back a newly
accepted command removes both its NodeRun and EventLog/Outbox notice. Workbench
functional regression plus three PostgreSQL scenarios: 25 passed, no skips
(`tmp/v1-d1-20260909/event-boundary.xml`); focused typing/lint passed.
Synchronous director checkpoints remain until durable consumption is wired.
Inbox, wakeup, separate worker and failure-isolation acceptance are outstanding;
this incremental evidence is not D2 completion.

Migration 0062 and director-owned Inbox/Wakeup models now persist receipt and
pending work in one transaction. Intake re-reads the scoped EventLog and validates
the typed notice rather than accepting queue-supplied execution data. A unique
consumer/event key deduplicates intake. PostgreSQL test
`test_director_inbox_pg.py` passed (no skips): rollback leaves neither record,
concurrent intake retains one pending wakeup, and redelivery after completion
does not reset it. Evidence: `tmp/v1-d1-20260909/inbox-pg.xml`. Focused lint and
typing pass. This test exercises fresh database sessions, not process termination
or Redis acknowledgment; the independent consumer/Worker and crash tests remain.

The independent consumer now resolves ownership through the bounded database
function `app.director_production_event_context(event_id)`, re-reads the persisted
notice under that scope, commits Inbox/Wakeup, then ACKs its own Redis consumer
group. Real Redis/PostgreSQL test passes with the app database role and injected
ACK connection failure: replacement consumer reclaims the pending message with
one durable wakeup; forged stream project/payload are ignored. Malformed messages
stay pending without starving valid siblings or fresh traffic. Evidence:
`tmp/v1-d1-20260909/stream-pg.xml`. A first test collection error from runtime
evaluation of Redis's generic type annotation was fixed with postponed annotations.

Consumer code is not yet registered as a deployed startup role. Wakeup dispatch,
bounded dead-letter handling, worker completion, actual process-kill recovery,
formal/editing/export events and removal of synchronous hooks still remain.

Director wakeup processing now obtains scoped production tracking DTOs, updates
checkpoints in its own transaction, and marks completion in that same commit.
The compatibility checkpoint adapter no longer imports production ORM or reads
raw snapshots. `test_director_wakeup_pg.py` passes under the app database role:
an injected failure after tracking leaves production queued, rolls back the
director turn and retains pending work; concurrent retries yield one completed
update. Evidence: `tmp/v1-d1-20260909/wakeup-pg.xml`; 24 related functional tests
also pass. Independent `app.workers.director.WorkerSettings` now declares a
separate queue and periodic durable-wakeup dispatch. It is not yet enabled in
Compose or proven with process-level Arq execution. Full D2 remains incomplete.

## 2026-09-10 continuation

Real Arq queue dispatch and burst Worker execution now pass in the isolated
Redis/PG test: dispatch replay produces one queued job, intake outage does not
block an already committed wakeup, and completed work is no longer dispatched.
The initial failure was Windows Arq cleanup referencing Unix SIGUSR1 after
successful execution; the test now releases its completed-worker resources
explicitly on Windows. Actual separate-process kill/restart is still outstanding.

Workbench generation/Formal writes now commit notices without invoking director
checkpoints, and receipt reads no longer query DirectorTurn. The optional
`director_turn_id` response remains null; existing frontend does not consume it.
Functional tests now deliver events in separate transactions and verify the same
next checkpoint after delivery, rather than requiring synchronous progression.
39 related functional tests pass; 10 Workbench tests additionally prove that a
broken director constructor cannot block AUTO/ASSIST/MANUAL production acceptance
(`workbench-isolation.xml`).

Default production Worker no longer registers director recovery/reconciliation.
The director Worker owns these and the notice/wakeup jobs. Release/build/offline
Compose definitions include worker-director, with no API/production dependency
on its health. Compose contract and Workbench tests pass (18 before the three
additional isolation cases); focused typing/lint pass. No shared deployment was
started. Remaining D2 work includes bounded retries/dead letters, processing
fairness, remaining lifecycle notices, process faults and full regressions.

Wakeup retry state now persists attempt_count, next_attempt_at, error class and
dead_letter_at. Each attempt runs checkpoint changes in a savepoint; on failure
only those changes roll back, while backoff survives commit. Attempts stop at
five and failed rows are excluded from pending discovery. The tests verify a
future due time suppresses execution, then advance only the isolated fixture's
due time to exercise retry/recovery and exhaustion without waiting wall-clock
minutes. Production remains queued and failed director changes do not leak.
13 tests pass (real PG/direct and real Arq cases plus Workbench API), evidence
`tmp/v1-d1-20260909/wakeup-retry.xml`. Operator replay and malformed-stream
dead-letter handling remain outstanding; database retry state is not evidence
of process-kill recovery or completed D2.

Malformed event intake now quarantines permanent validation/missing-event errors
after five Redis deliveries. Lua checks current message ownership, writes only
source ID/validated event ID/error type to a separate dead-letter stream, and
ACKs atomically. A forced dead-letter write failure leaves the original pending;
real Redis/PG verification passes (`stream-pg.xml`). Infrastructure connection
errors remain recoverable and are not classified as malformed data.

Explicit database wakeup replay is owner-scoped, locks the failed row, verifies
the expected failure timestamp, writes an audit event, then resets retry state.
Repeated replay is a no-op after the first acceptance; a stale failure generation
cannot reset newer failures. The retry-exhaustion PG scenario now exercises
replay and successful recovery (three wakeup cases pass, `wakeup-pg.xml`). The
service still needs an operator-facing API/UI and corresponding authorization
regression; no claim of full product replay or separate-process recovery yet.

Real subprocess-kill verification now passes: a child using the app database
role pauses after uncommitted director tracking, is killed by its verified test
handle, and PostgreSQL rolls back that transaction. Production stays queued,
the pending wakeup survives, and a replacement handler finishes it. Evidence:
`tmp/v1-d1-20260909/process-kill.xml` (one selected case), and the updated four-case
wakeup suite. This covers one database transaction interruption point, not all
D7 process/checkpoint interruption points.

Migration 0063 adds a production-side terminal notice trigger for shot runs with
a frozen workbench plan. This is an implementation choice to cover scattered
completion/failure/recovery status writes; it emits only EventLog/Outbox records
and never calls director logic. The app-role PostgreSQL test verifies status
rollback also rolls back its notice; a committed failure notice is independently
consumed and advances the director to execution_failed. Four wakeup cases pass
in `terminal-notice.xml`. Migration only ran in newly created test databases.
Further success/cancel paths, late/out-of-order events, audit of all affected
recovery paths and full regression remain necessary.

Continuation 2026-09-10: full unit regression finished with 1023 passed and three
failures (`tmp/v1-d1-20260909/unit-regression.xml`). One legacy test still required
director recovery on the production worker. Replaced that expectation with both
production-worker exclusion and an awaited independent-worker startup recovery
assertion; all 18 director turn service tests pass. Two directory compliance
tests remain blocked by the pre-existing inaccessible historical worktree
`.worktrees/p10-v1-revalidation-20260901/backend/.venv/lib64` (WinError 1920).
That worktree was not modified; this is not a full green regression claim.

Four app-role PostgreSQL cases now deliver terminal notices before acceptance,
then repeat both notices: completed, cached (with a persisted completed source
run), cancelled, and completed_after_cancel. Each converges to one director turn
with the current candidate-confirmation/failure action, preserving production
status and creating no ProviderOperation. Evidence: `late-events.xml`, four pass.
Initial test-authoring errors (wrong Artifact import and missing cached source)
were corrected without relaxing production constraints. This exercises notice
delivery/reconciliation, not actual provider completion or cache selection.
The changed tests pass Ruff and tracked diff whitespace checks. Full D2 and the
remaining D3-D8/manual-final-film acceptance are still incomplete.

ProposalService no longer invokes DirectorBusinessCheckpoints in the decision
transaction. A typed proposal_decided notice uses the same EventLog/Outbox and
durable intake, scoped by proposal ID; the consumer re-reads canonical item
decisions independently. Pure duplicate/conflicting decision replay emits no
second notice. Intake validates both aggregate ID and type for all notice kinds.
The immediate rejection gate already queries canonical rejected proposal items;
tests prove it blocks unchanged context before director consumption.

Evidence: `proposal-boundary.xml` has 53 functional passes across partial apply,
story/editing commands, stale proposals and next actions; another 17 Workbench
and contract tests pass. `proposal-notice-pg.xml` has four real PostgreSQL/Redis
passes (two app-role proposal scenarios plus intake and stream regression).
The proposal cases prove rollback removes notice and mutation, director failure
cannot prevent decision commit, repeat acceptance does not bump Shot version,
and independent delivery reaches the explicit accepted-changes review or closes
the rejected branch. The initial accepted-case test incorrectly expected a
completed turn; corrected to the existing mandatory confirmation state and
asserted accepted item identity/confirmation, without changing product behavior.
The unit fixture now loads model metadata before table creation; initial missing
Inbox table was a fixture initialization issue. Changed source passes mypy and
changed source/tests pass Ruff. No paid Provider, shared database migration,
commit or formal D2 completion occurred in this continuation.

Quality integration continuation: `docker-compose.quality.yml` now supplies an
isolated redis-quality service, healthy dependency and TEST_DIRECTOR_REDIS_URL.
Existing CI invokes backend-quality with dependencies, and its integration
command already uses --fail-on-skip; no weaker skip policy was introduced.
Compose configuration parses successfully. Full backend mypy passes (262 source
files), and full Ruff passes across app/tests/migrations. Container image build
and the complete container gate have not run for this source.

`publish-recovery-pg.xml` records two real PG/Redis stream tests passing. The new
case uses the deployed RedisStreamPublisher with only a randomized stream name:
after XADD succeeds, the database publish transaction rolls back; a fresh
transaction publishes again and commits. Redis contains two messages with the
same event ID while the stopped director has no Inbox. Restarted intake ACKs
both and persists exactly one Inbox/pending Wakeup. Assertions read Redis itself,
so the test-environment memory fallback cannot satisfy them. This is explicit
transaction rollback fault injection, not a publisher OS-process-kill test, and
does not by itself prove end-to-end single business execution. Existing tests
cover subsequent wakeup replay separately. No deployment or paid calls occurred.

## Final local convergence

All production/Proposal writes now commit typed notices without a synchronous
Director call. Independent Redis intake, durable Inbox/wakeup, bounded retry and
dead-letter replay, separate Arq worker registration, process-exit recovery,
terminal late facts and default-worker separation are active in the current
Compose definitions. The final repository Docker Gate starts real isolated
PostgreSQL and Redis, runs all 74 integration cases with `--fail-on-skip`, and
passes. D2's remaining boundary is formal commit/lifecycle evidence; the earlier
incremental “remaining” paragraphs are preserved as implementation history.
