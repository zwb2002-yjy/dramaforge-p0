# V1-D5-DIRECTOR-ENGINE-MIGRATION-20260910

Status: IN_PROGRESS, additive local implementation only.

Authority: Owner implementation §9 and D4 ADR 0007. D1 stable contracts, D2
independent wakeups, D3 invocation journal and the locally validated D4 adapter
are inputs. Existing production NodeRun/Outbox/Arq/ProviderOperation/Artifact
remain unchanged and authoritative.

Initial fact: the repository had an independent director Arq worker and durable
Inbox/wakeup path, but wakeups invoked only legacy DirectorBusinessCheckpoints.
DirectorTurn had no engine binding or runtime execution identity. The D4
LangGraph adapter was not registered. Its stock PostgreSQL checkpointer had been
tested only in per-test databases and was not provisioned or isolated for
product use. Legacy recovery jobs owned all existing turns.

Outcome: add per-Turn immutable engine/state/runtime-execution binding, a durable
lease with fencing epoch, persistent resume claims and stop control, a projector
to existing Turn/API state, and project-scoped checkpointer access through a
dedicated role/schema. Route only explicitly enabled new turns to LangGraph;
legacy in-flight turns remain on TurnService. Independent director workers must
release at interrupts and verify lease/epoch before actions and checkpoint
writes. Rollback changes future routing only.

Owned paths: additive migration/model registry, director runtime state/control/
projector/engine routing, independent director worker/wakeup adapter, settings
and compose wiring, focused real PG/Redis/process tests, and this contract. D6
full Story/Shot/Editing UI/tool reconnection, paid models, shared database
migration, deployment and removal of the legacy reader are outside this task.

Acceptance: additive migration round trip; old rows remain legacy and readable;
new rows bind once to exact engine/state/execution; different project/workspace,
duplicate business IDs, forged execution IDs and connection reuse cannot expose
checkpoints; one valid lease holder advances; expired holder cannot write or
submit after takeover; duplicate signals produce one effect; waiting returns the
worker; default production worker contains no new director engine jobs; rollback
does not move already-bound turns. Local tests are not formal completion without
reviewed commit/lifecycle evidence.

## Local implementation result

Alembic head `20260910_0066` now adds an immutable per-Turn engine/state/
execution binding, independent graph revision projection, runtime control row,
lease epoch, durable signal journal and runtime wakeup queue. A new Turn is
bound only when `DIRECTOR_RUNTIME_ENGINE=langgraph` and its creation result is
explicitly `created=True`; changing the setting never binds an existing blank
or legacy Turn. The legacy recovery cron, next-action reconcile and business
checkpoint adapter skip engine-bound Turns.

The LangGraph checkpointer uses schema `director_runtime_checkpoints` through
role `dramaforge_director_checkpoint`. Alembic, rather than a runtime call to
`saver.setup()`, provisions the exact 3.1.2 table/migration layout. The role has
no business-table grant, `dramaforge_app` has no checkpoint-schema grant, and
FORCE RLS requires the adapter-owned project setting on all three data tables.
Each graph operation opens one project-pinned connection and closes it before
reuse; caller-supplied libpq options are rejected. Worker startup verifies the
schema version and fails closed when the private store is unavailable.

The versioned start API returns 202 after committing only the server-derived
Proposal context, Turn binding and durable wakeup. The independent Director
Arq queue claims that database wakeup, commits the claim, obtains the runtime
lease, and runs one bounded graph segment. User/production signals are journaled
before graph mutation. The control-row lock remains held across checkpoint
writes, and the stable persisted production authorization key is the only key
accepted by the domain tool. Waiting clears the lease and exits the job. A
duplicate wakeup or signal projects the same graph revision without another
Turn revision or NodeRun. Stop has a separate versioned endpoint and records
both the control request and durable wakeup; legacy endpoints reject a bound
Turn instead of becoming a second engine.

Local evidence on the isolated PostgreSQL/Redis quality services:

- 48 focused unit/API/compose tests pass for graph behavior, immutable routing,
  legacy Turn handling and deployment structure.
- 9 D4/D5 PostgreSQL tests pass for checkpoint compatibility, project RLS,
  connection replacement, process exits, binding/fencing, committed-signal
  recovery, migration down/up and the real Proposal/authorization tool paths.
- The Proposal flow is dispatched through real Redis/Arq while the event intake
  is intentionally unavailable; the durable start wakeup still runs once.
- 11 existing D2 PostgreSQL/Redis tests pass after event routing changed,
  including ACK gaps, replay, process kill, dead letter and terminal facts.
- The production-authorization flow creates exactly one additional canonical
  video NodeRun and stores its existing `approved:<decision-id>` command key;
  no alternate ProductionGraph, ProviderOperation or Artifact truth was added.

No paid Provider/model request, shared database migration, release deployment,
commit or Owner review was performed. The status therefore remains IN_PROGRESS
under the repository lifecycle protocol even though the bounded D5 behavior is
locally implemented and verified. D6 still owns the complete Story/Shot/
Review/Repair/Editing UI reconnection and mode semantics.
