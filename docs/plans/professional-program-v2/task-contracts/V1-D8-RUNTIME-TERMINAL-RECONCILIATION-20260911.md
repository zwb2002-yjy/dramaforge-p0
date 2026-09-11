# V1-D8-RUNTIME-TERMINAL-RECONCILIATION-20260911

Status: IMPLEMENTED, COMMITTED AND LOCALLY VERIFIED; FOLLOW-UP REVIEW PENDING.

Task ID: `v1-d8-runtime-terminal-reconciliation-20260911`.

## Authority and current evidence

This bounded correction follows Owner design §§8-12, Owner implementation
§§11-12, and D7/D8. PR #79 merged the base D0-D8 implementation into `main` as
`986cd5e`. The retained isolated acceptance database is the authority for the
new finding: eight runtime-bound media Turns remained at
`awaiting_execution / production_fact` after their NodeRuns were terminal.

The accepted films are still valid. The template MP4 is 3,806,685 bytes,
19.239 seconds, H.264/AAC, with SHA-256
`5a14cb93b2a2d52c0dda03bfa456dd9910a8cfaa0feebb99a1984daa26b7f67b`;
the Free/ASSIST MP4 is 3,073,964 bytes with the same duration/codecs and SHA-256
`942b026c88d7d104015c50cd8685eb351cbd9a8f1e35f9a5d7d1f966df2a68d9`.
Their independent SRTs contain four and three cues. The Director continuation
claim, rather than the delivery bytes, was wrong.

DeepSeek execution is also settled: six persisted LiteLLM responses identify
`anthropic/deepseek-v4-flash`; four validated, two failed closed as
`INVALID_DIRECTOR_TEXT_OUTPUT`, and zero remain in an unknown state.

## Outcome and boundaries

Terminal production and Formal facts must advance a bound Director Turn even
when delivery is duplicated, delayed, or reordered. A fact may enter only the
matching graph checkpoint. Reconciliation must read canonical application facts
and enqueue a durable, deduplicated, revision-fenced signal. It must not create a
second authorization, NodeRun, ProviderOperation, or model call.

Owned paths are the Director runtime fact adapter/reconciler, production-event
wakeup filtering, the existing low-rate worker job, one PostgreSQL flow test,
the D7/D8 records and this contract. No migration, production deployment,
provider retry, media regeneration, engine replacement or new product behavior
is in scope.

## Implementation

- `DirectorDomainRuntimeTools.execution_fact` explicitly maps the six fields in
  strict `ExecutionFact`; tracking-only identity fields no longer violate its
  `extra="forbid"` contract.
- `_enqueue_runtime_event` gates Proposal, execution and Formal notices by the
  Turn's actual wait state. Formal additionally must match the one linked
  NodeRun's stage and result Artifact.
- `DirectorRuntimeFactReconciler` finds already-committed terminal execution or
  matching Formal events, derives a deterministic UUID5 signal, and uses the
  existing wakeup dedupe service.
- `reconcile_waiting_director_turns` invokes that adapter for engine-bound Turns
  while retaining the legacy reconciler for unbound Turns.

## Verification and limitations

- Correction commit: `4e61d6f`.
- Expanded PostgreSQL flow: Formal delivered before completion creates no
  runtime signal; terminal completion advances to `confirm_candidate`; low-rate
  reconciliation consumes the earlier Formal; final state is
  `completed / candidate_confirmed`; the fixture remains at exactly two
  NodeRuns (one upstream seed and one authorized video run).
- Disposable clone of the real acceptance DB: six clean historical Turns
  recovered to `candidate_confirmed`; ProviderOperation count stayed 27. Two
  checkpoints already poisoned by the old out-of-order delivery remain in the
  disposable clone. The original evidence DB was never mutated. New delivery is
  prevented from creating that state by the PostgreSQL regression above.
- Complete Docker quality Gate: directory and canonical checks; Ruff; mypy 278;
  backend unit 1,041; migration upgrade/check through 0066; PostgreSQL 74;
  generated API equivalence; frontend format/lint/type, unit 155 and build;
  Playwright 20; local LiteLLM proxy 5. Exit code 0. Logs:
  `tmp/v1-d8-runtime-hotfix-quality-20260911.stdout.log` and `.stderr.log`.
- Consolidated machine-readable counts, hashes and merge identity:
  `tmp/v1-d8-runtime-terminal-reconciliation-20260911/evidence.json`.
- No external Provider or text-model call was made by the correction or its
  tests.

The retained `127.0.0.1:8088` stack is no longer needed once this evidence is
captured. It may be stopped with named volumes and local MP4/SRT evidence kept.
The disposable debug database may be deleted. The code is ready for a bounded
follow-up `dev -> main` review; integration remains an Owner decision.
