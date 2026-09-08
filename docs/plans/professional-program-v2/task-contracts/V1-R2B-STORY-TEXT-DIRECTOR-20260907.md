# V1 R2b — Brief-to-script Director proposal

**Task:** `v1-r2b-story-text-director-20260907`\
**Parent:** G1 / G4 / R2a\
**Status:** COMPLETE\
**Baseline:** `dev@957e9895240ba4bd09fe2098234999e2a176b996`

## Current evidence and problem

The existing Story path safely parses a user-supplied Markdown draft into typed
proposal items and applies only explicit decisions. It does not generate that
draft from a creative brief. R2a now provides the audited text-model turn needed
to add generation without placing network I/O inside the parser or bypassing the
proposal boundary.

## Outcome

- Add a strict structured Story draft candidate and deterministic Markdown
  renderer in a dedicated generation service.
- Resolve only `planning.script`, invoke the R2a text bridge, render a parser-
  compatible draft, and pass it to the existing `create_story_proposal` service.
- Link the DirectorTurn to the resulting proposal and return proposal, generated
  draft and invocation evidence as one response.
- Add a brief-only action to the current Script workspace while preserving the
  manual Markdown proposal action and all per-item accept/reject behavior.

## Owned paths

- `backend/app/director/story_generation.py`
- `backend/app/director/text_transport.py` only for proposal-link finalization
- `backend/app/api/v1/story.py`
- focused Story generation/API/unit tests
- `frontend/src/features/script/api.ts`
- `frontend/src/features/script/ScriptWorkspace.tsx`
- `frontend/src/shared/api/generated.ts` and focused frontend unit/E2E fixtures
- this contract and Goal status

## Invariants

- Model generation creates only DirectorTurn, Director thread/message, proposal
  and proposal items. Episode, Scene, Shot and ScriptDocument remain unchanged
  until explicit item decisions are applied through the existing registry.
- Model output is strict structured data; it cannot supply arbitrary commands,
  SQL, URLs, Provider fields, IDs or executable payloads.
- One request key drives both text-turn and Story-proposal idempotency. Same
  context returns the same turn/proposal; changed context with the same key
  conflicts.
- Parse/proposal failure is recorded on the turn. No deterministic story is
  substituted after model failure.
- `planning.script` is the only slot for this task; no hidden Director model or
  fallback is introduced.

## Acceptance

1. A brief alone yields a typed, parser-compatible Story proposal and visible
   draft/model/turn evidence.
2. Before decisions there are zero new Canonical ScriptDocument/Episode/Scene/
   Shot rows. Accepting a subset applies only that subset; rejecting items leaves
   them absent.
3. Same-key replay performs no second model call and creates no duplicate
   proposal; same key with changed brief fails closed.
4. Invalid structure, parser failure, cross-project scope, unavailable model and
   malicious fields fail closed with manual authoring still available.
5. Full relevant backend, PostgreSQL, frontend and E2E gates pass.

## Result

- `StoryGenerationService` freezes the current project/Story versions and
  invokes only `planning.script`. Its strict Episode/Scene/Shot result contains
  no command or persistence identities and is rendered through a newline-safe,
  parser-compatible Markdown boundary before entering the existing Story
  proposal service.
- The new brief-only API returns the exact generated draft, typed proposal and
  R2a invocation evidence. The DirectorTurn is linked to the proposal and waits
  for user decisions; model or parser failures are durable, manual-safe failures.
- Canonical Story is re-read after inference. A concurrent Script/Episode/Scene/
  Shot change marks the late turn `stale` and prevents proposal creation.
- Controlled acceptance proves zero ScriptDocument/Episode/Scene/Shot writes
  before decisions; same-key replay has one model call and one proposal; changed
  brief conflicts; a selected subset applies alone; reject-all keeps Story
  empty; malicious output repairs at most once; and missing model configuration
  never substitutes a deterministic story.
- Script workspace keeps manual Markdown authoring and adds a distinct
  “Brief 生成剧本提案” action. It displays the returned draft/model/turn evidence
  and continues through the same item checkboxes and accept/reject commands.
- Same-candidate backend Gate: directory/canonical checks, Ruff, MyPy `239`
  source files, `916` unit tests, migration drift check, `21` PostgreSQL
  integration tests and OpenAPI export all PASS.
- Same-candidate frontend source was run with the already locked R2a dependency
  image after a transient npm Registry reset: API check, Prettier, ESLint,
  native TypeScript 7, production build PASS; Vitest `28` files / `141` tests
  PASS; Playwright `19` PASS. No dependency, provider, paid-media or Canonical
  production write was introduced by the verification setup.
- SHA-256 comparison confirms all nine verified runtime/API/test files match the
  integration and isolated quality worktrees; `git diff --check` PASS.

## Next

R2c maps editing advice explicitly to `planning.storyboard`, uses the same text
turn evidence, and preserves the existing EditSession preview/apply/save and
version recheck boundaries without triggering media regeneration.
