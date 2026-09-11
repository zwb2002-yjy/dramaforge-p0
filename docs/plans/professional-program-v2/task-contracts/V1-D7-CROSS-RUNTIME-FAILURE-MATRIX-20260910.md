# V1-D7-CROSS-RUNTIME-FAILURE-MATRIX-20260910

Status: BASE IMPLEMENTATION MERGED; POST-MERGE CORRECTION VERIFIED LOCALLY.

Authority: Owner implementation §11, Owner design §§6–10, D1–D6 contracts and
the current Professional production/runtime facts. This contract adds evidence
for the Director/production boundary; it does not reopen the completed R5
record or inherit its PASS as proof for the new engine.

Outcome: prove that app transactions, Director Inbox/wakeups, checkpoint
transactions and production execution converge after crash, replay, duplicate,
reordering, stop and tenant-boundary scenarios. A Director failure cannot roll
back or recreate an accepted production command. Manual production and Final
Film remain independent of the Director process.

Owned paths: Director runtime control/executor/wakeups, existing fault tests,
focused new failure tests, evidence mapping and this contract. Paid Provider
calls, shared database mutation, deployment, merge and release are outside this
local run.

Failure evidence matrix (2026-09-10):

| ID | Local evidence | Result |
|---|---|---|
| F01 Director stopped | `test_application_duplicate_acceptance_needs_no_director`; `test_manual_director_off_delivery_pg` | PASS |
| F02 text timeout | `test_director_text_transport.py` timeout/failure cases; production facts untouched | PASS |
| F03 unknown text submission | `test_recovery_fails_unknown_text_submission_once_without_media_write` | PASS |
| F04 result persisted before checkpoint crash | invocation journal replay tests in `test_director_invocations_pg.py` | PASS |
| F05 command accepted before checkpoint crash | `test_executor_recovers_committed_signal_and_projects_once` and exact receipt replay | PASS |
| F06 duplicate concurrent resume | in-memory concurrent resume plus PG composite signal claim | PASS |
| F07 expired old worker / stop-before-start | lease epoch takeover/old guard rejection plus `test_stop_before_first_checkpoint_settles_start_and_stop_wakeups` | PASS |
| F08 Outbox publish/ack exit | real Redis stream reclaim tests | PASS |
| F09 Inbox committed while queue unavailable | durable Inbox/wakeup compensation tests | PASS |
| F10 duplicate/out-of-order completion | terminal notice and business checkpoint monotonicity tests | PASS |
| F11 grant revoke race | PostgreSQL lock serialization in `test_production_application_pg.py` | PASS |
| F12 design/mode change while waiting | Shot stale tests plus project Turn/control invalidation | PASS |
| F13 production done before Director consumes | production facts read/reconcile and delayed wakeup tests | PASS |
| F14 remote task ID restart | controlled plugin recovery matrix; remote create delta zero | PASS |
| F15 stop Director, media succeeds late | late completed/cached/cancel variants in Director wakeup tests | PASS |
| F16 cross-tenant identifiers | app RLS plus dedicated checkpoint-role project scope tests | PASS |
| F17 mixed engines | immutable per-Turn engine routing; bound Turns rejected by legacy endpoints | PASS |
| F18 subtitle/Timeline rerender | PostgreSQL paired export and real FFmpeg tests; image/video delta zero | PASS |

Verification summary:

- D1–D6 PostgreSQL/Redis/process group: 25 passed. The original R5 recovery
  matrix was rerun against a migrated isolated PostgreSQL database: 18 passed.
- Full backend unit regression after D6: 1,041 passed. Full frontend unit suite:
  154 passed, followed by lint, TypeScript and production build. Focused browser
  regression passed 6 Playwright cases for AUTO delegation and the
  Assistant/manual/Editing boundaries.
- The complete current Linux integration collection excluding only the separate
  isolated LiteLLM proxy test contains 74 tests and passes in 247.03 seconds.
  No skipped test was accepted because the run used `--fail-on-skip`.
- Real FFmpeg plus PostgreSQL SRT lineage: 2 passed. The new MANUAL director-off
  real-render path passed independently and generated local MP4/SRT evidence.
- The repository's single Docker quality command passes from the current
  worktree: directory/canonical checks, Ruff, mypy (277 files), 1,041 backend
  unit tests, Alembic upgrade/check through 0066, the 74 integration tests,
  generated API equivalence, Prettier/ESLint/TypeScript, 154 frontend unit tests,
  production build, 20 Playwright tests and 5 isolated LiteLLM proxy tests.
- That gate initially exposed a real orchestration defect: Redis tests received
  `TEST_DIRECTOR_REDIS_URL` while `run_quality_in_docker.ps1` started only
  PostgreSQL before `--no-deps`. The script now starts and health-checks both
  dependencies. All 13 affected Director/Redis tests and then the whole Gate
  passed; the failed run remains part of the evidence history.
- All controlled media/text fixtures are explicitly local; external Provider and
  text model calls were zero. Failures and skips are not relabelled as PASS.
- Re-verification (2026-09-10, later run). Three frontend files were changed at
  18:46:47 after the D8 identity manifest was written, so the whole Gate was run
  again from the current worktree: Ruff, mypy (277 files), 1,041 backend unit
  tests, Alembic through `20260910_0066` plus `alembic check`, 74 integration
  tests, generated-API equivalence, Prettier/ESLint/TypeScript, 155 frontend
  unit tests, the production build, 20 Playwright tests and 5 isolated LiteLLM
  proxy tests all pass. The frontend unit count is 155 here rather than the 154
  recorded above because the later edit added one test. The re-derived 796-file
  manifest matches both quality images byte-for-byte; full detail is in
  `tmp/v1-d8-identity-20260910/`.

Post-merge correction (2026-09-11):

- PR #79 merged the D0-D8 base into `main` as merge commit `986cd5e`. A direct
  audit of the retained acceptance database then contradicted the broad F10/F13
  conclusion above: all eight media-bound runtime Turns remained at
  `awaiting_execution / production_fact`, despite their canonical NodeRuns being
  terminal. Twenty-three earlier runtime wakeups had dead-lettered.
- The first root cause was an invalid projection from the richer
  `ExecutionTrackingFact` into the strict `ExecutionFact`; four tracking-only
  fields were passed to a schema with `extra="forbid"`. The second was event
  ordering: a `formal_selected` notice could be delivered while the graph still
  expected `production_fact`, poisoning that historical checkpoint.
- Correction commit `4e61d6f` explicitly projects the six production fact
  fields, filters event wakeups by the Turn's current checkpoint, and adds a
  durable low-rate reconciler. The reconciler reads existing canonical
  `NodeRun`/Formal/EventLog facts and enqueues a revision-fenced signal; it never
  creates or resubmits a production command.
- The expanded PostgreSQL test delivers Formal before terminal execution,
  proves that the early notice cannot enter the wrong checkpoint, resumes from
  the terminal fact, then recovers the already-committed Formal fact. The Turn
  ends at `candidate_confirmed` and the NodeRun count remains exactly two in the
  fixture (one seeded upstream keyframe plus the single authorized video run).
- A disposable clone of the real acceptance database recovered six clean
  historical Turns without adding a ProviderOperation (27 before and after).
  Two already-poisoned historical checkpoints remain intentionally unrepaired;
  the new event gate prevents that state for new Turns. The retained original
  acceptance database was not mutated.
- The complete Docker quality Gate on the correction source passed: directory
  and canonical checks, Ruff, mypy (278 files), 1,041 backend unit tests,
  Alembic through 0066 plus `alembic check`, 74 PostgreSQL integration tests,
  generated API equivalence, frontend formatting/lint/type checks, 155 frontend
  tests, build, 20 Playwright tests and 5 isolated LiteLLM proxy tests. Full log:
  `tmp/v1-d8-runtime-hotfix-quality-20260911.stdout.log`.

F10 and F13 are therefore PASS for the correction source, while their original
2026-09-10 evidence is preserved above as an incomplete test claim rather than
rewritten as proof for candidate `3c728a3`.
