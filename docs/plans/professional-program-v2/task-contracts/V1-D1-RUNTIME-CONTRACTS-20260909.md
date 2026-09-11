# V1-D1-RUNTIME-CONTRACTS-20260909

Status: IN_PROGRESS (local implementation; no formal COMPLETED claim).
Dependency: D0 Owner sources registered and static baseline inspected. Live
environment inventory and D0 ledger recording remain outstanding; this task
does not mutate existing runtime data.

## Outcome and authority

Implement the D1 contracts from the registered September 9 Owner implementation
§5. Director consumes scoped production facts through an application port;
production commands and runtime signals expose application-owned types only.
Existing production identity, locks, receipts and validation remain in force.

## Current evidence / drift

At `4de7acd`, NextAction imports NodeRun/GraphVersion/ProductionGraph and reads
input_snapshot directly. Workbench already has command lookup, request hash,
project lock, shot version and fingerprint validation; reuse these services.
BusinessCheckpoints is a legacy synchronous adapter removed from the production
transaction in D2; do not disguise that remaining dependency as D1 completion.

## Owned paths / non-scope

`backend/app/contracts/`, `backend/app/production/application/`,
`backend/app/director/runtime/ports.py`, `backend/app/director/runtime/__init__.py`,
`backend/app/director/next_action.py`, relevant new contract/read-port unit tests,
`backend/app/api/v1/workbench.py`, this contract and ignored D1 evidence.
`backend/tests/integration/test_production_application_pg.py` verifies the
extracted application directly with PostgreSQL and no director record.
The workbench request schemas and guarded execution are extracted without
changing the public schema or removing synchronous checkpoints before D2.
No Provider calls, UI changes, legacy workflow replacement, or framework
dependency activation. The additive migration scope is specified below.

Scope refinement for persisted authorization: own
`backend/app/production/command_models.py`, migration `20260909_0061`, and
`backend/app/shared/model_registry.py`. The additive command authorization journal
binds one explicitly approved action to its exact body, model plan and profile
version before submission. It references the existing NodeRun receipt; it is
not a second production execution store. Migration tests run only against the
isolated PostgreSQL quality target. No existing database is migrated here.

## Success criteria and verification

Scoped fact lookup rejects missing, cross-project and cross-shot execution IDs;
the director receives immutable DTOs instead of ORM objects or raw snapshots.
Preserve next-action failure, candidate, Formal and MANUAL behavior. Stable
command and signal contracts reject framework-private or arbitrary action data.
Run focused read-port and NextAction tests, lint and typing for affected modules.
Production receipt identity and concurrent authorization acceptance still require
the Owner-specified PostgreSQL integration evidence; SQLite is only functional
feedback. D1 is not complete on DTO definitions or static import checks alone.

Formal completion requires the full §5.4 boundary checks, real PostgreSQL
idempotency/concurrency checks, reviewed scoped commit and lifecycle evidence.
D2 transaction migration follows without recreating production storage.

## Local evidence (not whole-package completion)

- Functional tests: 45 passed across Workbench API/execution, NextAction and
  scoped production reads. Existing test harness disables live providers.
- Existing PostgreSQL receipt/mode-lock integration: 1 passed, no skips,
  `tmp/v1-d1-20260909/command-pg.xml`.
- New shared application PostgreSQL test: 1 passed, no skips,
  `tmp/v1-d1-20260909/application-pg.xml`. Two concurrent identical commands
  return the same receipt; changed payload conflicts; zero DirectorTurn and
  ProviderOperation rows are created by acceptance.
- Affected application typing and lint passed before the event contract addition;
  rerun for the final D1 set. Alembic reports sole head `20260908_0060`.
- Isolated quality PostgreSQL container uses the existing compose image,
  project `dramaforge-v1-d1-20260909`, localhost port 55439. No migrations were
  applied to the pre-existing application databases.
- Remaining: durable command/grant journal and authorization race checks,
  full boundary convergence with D2, OpenAPI equivalence, reviewed commit and
  truthful lifecycle registration. Runtime ports alone are not an engine.

Subsequent verification: workbench OpenAPI is exactly equal to HEAD for all
11 paths (`tmp/v1-d1-20260909/openapi-equivalence.json`). The PostgreSQL
application test also verifies cached stale Shot rejection after another
transaction saves a newer version, and successful replay of an earlier accepted
command despite that edit. Acceptance now refreshes Shot under its row lock.
The control boundary rejects injected actor/workspace/authorization fields in
stage bodies and opaque checkpoint/tool state in resume signals. These tests
prove input constraints; persisted authorization and runtime execution remain
outstanding. Current verification output is in `tmp/v1-d1-20260909/focused.xml`.

Persisted single-action authorization is now implemented in the production
application and migration 0061. Its exact body/profile version/expiry and stable
key survive separate sessions; accepted rows reference existing NodeRuns.
The PostgreSQL application test passes concurrent grant submission and revoked
grant rejection. No live database migration or Provider call was made. Still
required: explicit revoke-vs-submit lock-race, mode/expiry/isolation cases,
decision idempotency integration and the product decision entry point. The
authorization service is not yet exposed as a model tool or product API.

Further PostgreSQL evidence: approval now requires a stable decision ID, used
as the persisted command key. Same decision/body/target/expiry returns the
original grant; changed input conflicts rather than issuing another permission.
Tests verify MANUAL suppression, invalidation after switching back to AUTO with
a newer profile, and receipt replay for already accepted work. The revoke race
holds a real transaction, observes `pg_blocking_pids` for submission, commits
revocation, and verifies rejection. This passed without skips in the updated
`application-pg.xml`; lint and focused typing also pass. Expiry, cross-scope RLS,
product decision integration and D2–D8 still remain.

Expiry and cross-project checks subsequently pass with the real application
database role: expired grants reject submission, another project's scope cannot
read or update the grant, and service lookup rejects the foreign grant ID. No
ProviderOperation is created and the pre-existing NodeRun ID set is unchanged.
The first version of this assertion incorrectly assumed an empty database;
inspection confirmed `_seed_video_shot` creates the completed keyframe NodeRun.
The corrected assertion compares actual before/after IDs, preserving the
requirement that rejected authorization creates no new execution.

## Final local convergence

The chronological gaps above are now closed by D2–D8. The one-shot
authorization is exposed through the AUTO delegation product API, reuses the
same production acceptance lock and exact frozen `ExecutionBody`, and is the
only authorization reference accepted by the Director domain tool. ASSIST and
MANUAL reject new delegation. The current Docker Gate covers expiry,
revoke/submit serialization, idempotent decision replay, cross-project RLS and
the exact one-NodeRun result. D1's remaining boundary is formal commit/lifecycle
evidence rather than an unimplemented contract or product entry point.
