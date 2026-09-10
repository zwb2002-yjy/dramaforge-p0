# V1-D4-LANGGRAPH-VALIDATION-20260910

Status: IN_PROGRESS, bounded local validation only.

Authority: Owner implementation §8 and Owner design §4, registered by the
seven-plan README. D1 stable contracts and the locally integrated D3 invocation
boundary are prerequisites. D2 formal closure remains separate.

Current fact: the Python backend has DirectorTurn, RuntimePort DTOs, durable
inbox/wakeup, explicit production commands/receipts, ContextBuilder,
InvocationService and a session-free TextModelPort. It has no LangGraph package,
checkpointer, engine routing or validated persistent interrupt/resume slice.

Outcome: evaluate one pinned Python LangGraph version behind the existing
DirectorRuntimePort. The slice must create a bounded state graph, pause without
holding a worker, resume from persisted state, keep business decisions and
production receipts in DramaForge DTOs, and expose engine/state versions. It
must prove duplicate resume does not advance twice and SDK state cannot create
Formal, Artifact or production success. No live Provider or media call is
needed for this control-flow validation.

Owned paths: backend dependency/lock files, director runtime LangGraph adapter
and state contracts, isolated checkpoint support required by the slice, focused
unit/PG/process tests, a D4 decision record, and this contract. D5 activation for
new production turns, UI work, shared database migration, Pi/Claude adapters,
paid model calls and production deployment are outside this task.

Hard gates evaluated here: H1 persistent interrupt/resume, H2 receipt replay
through a fake stable command port, H3 duplicate/concurrent resume, H4 stale or
MANUAL gate before command, H5 project-scoped checkpoint identity, H7 bounded
steps/stop, H8 business truth outside SDK state, H9 no work while interrupted,
and H10 engine/state identity. H6 live model identity remains NOT_RUN until the
configured-channel evidence authorized for D3/D8.

Evidence must record actual package version, Python version, state schema,
source SHA, measured cold import/runtime where available, pass/fail/not-run,
and exact test boundaries. Local green tests do not activate the engine or
complete D4/D0-D8. If the main slice fails a hard gate and cannot be fixed within
this contract, record the failure before considering the Pi adapter.

## Local validation result

The locked environment resolves LangGraph 1.2.11 and PostgreSQL checkpointer
3.1.2 under Python 3.12. The `uv.lock` consistency check resolves 98 packages and
`pip check` reports no broken requirements. The implementation uses raw
StateGraph and the existing DramaForge ports; it does not add a LangChain model
wrapper, alternate model catalog or hosted LangSmith dependency.

The graph pauses for Proposal decision, ProductionFact and candidate
confirmation. RuntimeView now exposes engine and state-schema identities.
Command submission uses a stable key through the domain port; the graph stores
only its receipt. Resume validates project/workspace/actor/turn and expected
revision, then uses an injected persistent signal claim. Stop and max-step gates
close before a command. SDK state has no Formal, Artifact or NodeRun write port.

Four unit scenarios pass (`d4-langgraph-unit.xml`): full interrupt flow and
receipt reuse, cross-scope/stop/step limits, concurrent duplicate resume with one
effective production create, and domain authorization rejection before receipt.
Two isolated PostgreSQL scenarios pass (`d4-langgraph-process-pg.xml`): checkpoint
recovery across replaced connections, plus three child processes exiting after
the proposal, command-receipt and production-fact checkpoints. The latter keeps
one persisted command receipt and two claimed signals. The strict serializer has
pickle fallback disabled and no additional msgpack module allowlist.

ADR 0007 records the H1-H10 matrix and selects LangGraph for D5, conditionally on
D5 project-level checkpoint isolation, durable signal claims, engine binding and
legacy in-flight routing. One measured Windows cold-process import was about
1503 ms; it is not a capacity result. Live configured model latency/quality,
container cold start and steady-state memory remain NOT_RUN. The adapter is not
registered as the production engine, so this contract remains IN_PROGRESS until
formal commit/lifecycle evidence; the bounded selection result itself is locally
validated.

## Final local convergence

D5 now registers the selected adapter for explicitly enabled new Turns with an
immutable engine/state/execution binding, a dedicated checkpoint role/schema,
durable signal claims and legacy in-flight routing. D6 exercises it from the
product API and independent worker. The current full Docker Gate passes these
paths. Live configured-model quality and capacity measurements remain truthful
D8/operational NOT_RUN items; the LangGraph selection and hard control gates are
implemented locally.
