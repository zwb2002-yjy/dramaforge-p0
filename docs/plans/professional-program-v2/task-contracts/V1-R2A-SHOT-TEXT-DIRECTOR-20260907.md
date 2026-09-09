# V1 R2a — Real text Director bridge and Shot proposals

**Task:** `v1-r2a-shot-text-director-20260907`\
**Parent:** G1 / G4 / G6 / Model Supply\
**Status:** COMPLETE\
**Baseline:** `dev@a33533b5d54ea01bdecd4e68eb89d5758464a118`

## Current evidence and problem

- `TextGenerateRequest`, `LiteLLMModelAdapter`, logical text manifests and the
  `planning.*` profile slots are executable, but no Director business endpoint
  consumes them.
- Shot suggestion and proactive recommendation default to deterministic rule
  transports, so their current UI success cannot prove model inference.
- `ProviderOperation` is the media/NodeRun execution record after legacy removal;
  creating a fake media NodeRun for text would violate the canonical runtime.
  R2a therefore lands the planned `DirectorTurn` as the one-round Director and
  text-call record, without introducing a second production job system.
- A shot-scoped `AssistantContextBuilder` queries `Scene` with the Shot id before
  loading the Shot; the resulting Scene context is absent.

## Outcome

- Add one common structured text bridge over the configured profile slot and
  `CapabilityRouter`; Shot uses `planning.storyboard`.
- Persist one project/workspace/actor-scoped `DirectorTurn` per request key with
  context and output hashes, input versions, profile binding snapshot, selected
  and returned model identity, safe request/response summaries, usage, reported
  cost (or explicit unknown), status, and at most one schema-repair attempt.
- Make the default Shot suggestion and recommendation paths real-model paths.
  Deterministic transports remain available only when explicitly injected as
  fixtures; model failure never falls back to them.
- Re-read Shot version after inference. A late result becomes `stale` and cannot
  be returned as an applicable proposal.
- Return bounded invocation evidence with the proposal and show its model/turn
  identity in the existing proposal-only UI.
- Fix and test Shot-to-Scene context resolution.

## Owned paths

- `backend/app/director/text_transport.py`
- `backend/app/director/turn_models.py`
- `backend/app/director/suggestion.py`
- `backend/app/director/recommendation.py`
- `backend/app/director/assistant_context.py`
- `backend/app/shared/model_registry.py`
- `backend/app/api/v1/director.py` only if response wiring requires it
- the unique Alembic successor after `20260903_0055`
- focused backend unit/PostgreSQL migration tests, including current-head
  expectations in existing migration regressions
- `frontend/src/features/director/api.ts`
- `frontend/src/features/director/suggestion-types.ts`
- `frontend/src/features/director/ShotDirectorSuggestionPanel.tsx`
- `frontend/src/shared/api/generated.ts`
- focused frontend unit/E2E fixtures
- this contract and Goal status

## Invariants

- Text output is an untrusted proposal: strict typed validation and recursive
  execution-field rejection remain mandatory; no media record, Formal mutation,
  design save, or Provider fallback is created.
- No credential, authorization header, raw wire request, arbitrary URL, SQL or
  executable command is persisted or returned.
- The profile-selected model is frozen before dispatch. Schema repair uses the
  same selected model once; transport failure/unknown submission stops the turn.
- The text binding snapshot is the effective `ProductionModelProfile` id,
  version and slot. It is not misrepresented as a media
  `ProviderModelBinding`.
- A duplicate request key with the same context returns the stored validated
  result; a reused key with a different context fails closed.

## Acceptance

1. Two materially different Shot contexts sent through the same controlled
   model produce context-related typed proposals and distinct context/output
   hashes; each UI response identifies exactly one persisted turn.
2. A configured single `planning.storyboard` binding executes; absent or
   unusable configuration produces an explicit manual-safe failure and a failed
   turn, without a deterministic success.
3. Invalid JSON receives at most one same-model schema-repair call; a second
   invalid result fails. Forbidden nested execution fields fail typed validation.
4. Provider usage and actual reported cost are stored verbatim. Missing cost is
   `unknown`, never estimated.
5. Cross-project scope and stale input/output versions fail closed. Suggestion
   calls add no NodeRun, Artifact, candidate, Formal, or canonical Shot write.
6. Migration has one head, table constraints/indexes/RLS are verified in
   isolated PostgreSQL, and the focused/full relevant quality gates pass.

## Result

- The default Shot suggestion and proactive recommendation endpoints now use
  the configured `planning.storyboard` model through the existing capability
  router. Deterministic implementations are reachable only by explicit fixture
  injection, and every missing-model/provider failure remains manual-safe.
- `DirectorTurn` is the durable one-round decision and text-call record. It
  stores project/workspace/actor scope, idempotency and context identity,
  versions and intent, exact Profile binding snapshot, selected/returned model,
  safe summaries, validated output/hash, usage, reported cost or `unknown`, and
  the bounded repair count. It creates no fake media NodeRun or Artifact.
- Controlled transport acceptance proves two materially different Shot
  contexts produce different relevant proposals and context/output hashes;
  same-key replay performs no second model call; a changed context conflicts;
  late results become `stale`; invalid/forbidden output gets at most one
  same-model repair; and unconfigured execution never becomes rule success.
- The shot-scoped Assistant context now resolves its Scene through
  `Shot.scene_id`, with the episode/project scope checked.
- Migration `20260907_0056` is the single head. Fresh upgrade, autogenerate
  drift check, downgrade/re-upgrade, unique request key, bounded repair check,
  indexes and project RLS all pass in isolated PostgreSQL.
- Same-candidate backend Gate: directory and canonical-surface checks PASS;
  Ruff PASS; MyPy `238` source files PASS; backend unit `908` PASS; PostgreSQL
  integration `21` PASS; current OpenAPI export PASS. The official pinned
  LiteLLM Proxy mock-runtime integration is `5` PASS and performs no upstream
  paid request.
- Same-candidate frontend Gate against that OpenAPI: API generation check,
  Prettier, ESLint, native TypeScript 7, production build PASS; Vitest `28`
  files / `140` tests PASS; Playwright `18` PASS. UI evidence binds each shown
  proposal to the returned model and DirectorTurn id.
- SHA-256 comparison confirms the 20 verified runtime/test/API files are
  identical between the integration worktree and isolated quality worktree;
  `git diff --check` PASS. Real configured-model product evidence remains owned
  by R7, as required by the execution plan.

## Next

R2b adds brief-to-script generation through `planning.script` and passes the
validated draft to the existing typed Story proposal service without mutating
Canonical Story before user decisions.
