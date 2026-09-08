# V1 R3 — Effective creative intent and model adaptation closure

**Task:** `v1-r3-effective-creative-intent-20260908`\
**Parent:** G4 / Model Supply / R2\
**Status:** COMPLETE\
**Baseline:** `dev@07a614b378c65f4fab612d6b65da84d66643b71e`

## Current evidence and drift

- `CreativeCapabilityCompiler` records selected Skill identities but no Skill
  strategy/output content, and leaves `shot_director_intent_patch=None` even
  when a Shot Language pack is selected.
- Freeze writes only provenance into Scene/Shot JSON. No compiled creative
  content is available to the execution plan or Provider request.
- Workbench execution accepts browser-supplied prompt/semantic intent and does
  not consume frozen creative capabilities or continuity context. The browser
  happens to send current Shot values, but the server does not prove they match.
- Reference compilation classifies exact/approximate/unsupported, yet plan
  preview rejects warnings before the UI can show them; the browser therefore
  cannot obtain explicit approximation consent.
- Exact concrete model resolution, profile/binding failure semantics,
  fingerprinting, reference freezing and Worker reconstruction already exist
  and must be preserved rather than rebuilt.

## Outcome

- Compile and freeze a content-bearing effective creative intent with explicit
  source explanations and the fixed priority: user-confirmed value > accepted
  proposal > project override > pack default.
- Include actual selected Skill strategy/output/quality guidance and the typed
  Shot Language patch, not provenance alone.
- Freeze the effective content/hash onto existing Scene/Shot state and expose it
  in the current provenance read/UI. Do not add a second truth table.
- At plan preview, validate prompt and expected Shot version against server
  truth, merge only frozen Scene/Shot capability and continuity facts, compose a
  server-owned effective prompt/semantic intent, and freeze them into the plan.
- Let preview return warning-level approximations for display; fatal unsupported
  inputs still fail. Exact plans dispatch normally. Approximate plans require a
  separate explicit UI confirmation and a second accepted preview; any changed
  model, binding, reference or intent is surfaced before dispatch.

## Owned paths

- `backend/app/director/creative_capabilities/creative_compiler.py`
- `backend/app/director/creative_capabilities/shot_language_compiler.py`
- `backend/app/director/creative_capabilities/freeze.py`
- `backend/app/api/v1/creative_capabilities.py`
- `backend/app/production/workbench_execution.py`
- `backend/app/api/v1/workbench.py`
- `backend/app/production/repair_service.py` only to use authoritative prompts
- focused compiler/freeze/workbench/model-resolution tests
- `frontend/src/features/production/CreativeCapabilitiesPanel.tsx`
- `frontend/src/features/shots/api.ts`
- `frontend/src/features/shots/ShotProductionActions.tsx`
- generated OpenAPI types and focused frontend/E2E tests
- this contract and Goal status

## Invariants

- Scene/Shot/Project remain canonical creative facts. Frozen intent is a
  versioned snapshot inside their existing state, and NodeRun/ProviderOperation
  remain the only production execution truth.
- Unpersisted browser drafts cannot become execution input. The server rejects a
  prompt/version mismatch before Provider or NodeRun creation.
- Pack and Skill defaults never overwrite a user/accepted/project value.
  Overridden defaults remain explainable but are not appended to the wire prompt.
- Continuity uses the explicitly frozen Scene context; execution never infers a
  new “latest previous Shot” constraint.
- Unsupported is fatal. Approximate is never silently dropped or accepted.
- Preview and execution retain exact binding, connection/credential revision,
  reference fingerprints, accepted approximations and plan fingerprint.

## Acceptance

1. User `production_design=白色西装` beats a Style default `黑色西装`; only the
   white value enters effective intent/prompt, with the overridden default
   recorded as explanation.
2. User `camera_motion=static/no push` beats an accepted proposal/Shot Language
   `dolly_in`; the rejected push term is absent from plan and safe request summary.
3. A selected Skill contributes its strategy/output guidance and a selected Shot
   Language changes typed Shot semantics; provenance-only output fails the test.
4. A Scene’s explicit red-wardrobe/continuity snapshot is frozen into the plan
   and remains unchanged on Worker recovery; no runtime predecessor lookup.
5. Approximate reference is shown and cannot dispatch before explicit confirm;
   unsupported fails before paid submission. Changed profile/binding/reference
   between previews cannot silently dispatch another identity.
6. One valid video binding resolves normally; explicit unavailable binding does
   not switch; profile changes after preview fail fingerprint/identity checks.
7. Full backend, PostgreSQL, frontend and E2E gates pass.

## Result

- The compiler now materializes a versioned effective-intent snapshot with
  leaf-level sources and overridden-default explanations. Its fixed merge order
  is pack default → project override → accepted proposal → user-confirmed value;
  nested saved Shot framing/camera facts are normalized to the corresponding
  typed Shot Language fields, while empty form defaults do not suppress packs.
- Selected Skills contribute their real strategy, output contract and quality
  hints. Shot Language contributes a typed patch after explicit-value filtering.
  The snapshot and SHA-256 compiled hash are frozen inside the existing
  Scene/Shot state and exposed by the existing provenance read/UI.
- Workbench preview rejects unsaved prompts and stale Shot versions, reconstructs
  semantic intent from saved/frozen server facts, and puts the same effective
  prompt, continuity context, Skill guidance and snapshot hashes into the frozen
  plan and NodeRun. Later Scene/Shot edits do not change resumed plans.
- Warning-level reference approximations are visible in preview and require a
  second accepted preview plus an explicit UI action. Fatal unsupported inputs
  never dispatch. The confirmation compares model, binding/revisions, prompt,
  semantic intent, references/fingerprints and Shot version before queueing.
- Execution now locks the canonical Shot, rebuilds the plan once, verifies its
  fingerprint and accepted approximation set, and hands that same in-memory plan
  to queueing. Explicit unavailable bindings fail without fallback, and binding
  changes after preview are rejected before any Workbench NodeRun is created.
- Same-candidate backend checks: Ruff PASS; MyPy `239` source files PASS; `927`
  unit tests PASS; migration upgrade/drift PASS; PostgreSQL integration `21`
  tests PASS. Focused effective-intent/model/reference/repair regressions PASS.
- Same-candidate frontend checks: generated API check, Prettier, ESLint, native
  TypeScript 7 and production build PASS; Vitest `28` files / `145` tests PASS;
  Playwright `19` tests PASS. Verification used locked dependency images and
  made no paid or external Provider request.

## Next

R4 closes bounded Director advancement and recovery on top of the now-frozen
effective creative intent, without adding an autonomous execution path.
