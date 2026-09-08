# V1 R2c — Real text Director for Editing

**Task:** `v1-r2c-editing-text-director-20260908`\
**Parent:** G6 / R2a\
**Status:** COMPLETE\
**Baseline:** `dev@1228f60727f94a9ba05fff9cb13780311173a903`

## Current evidence and slot decision

Editing already has a strict, proposal-only Timeline plan, two EditSession
version checks, local preview/apply and explicit save. Its default transport is
deterministic and its context omits subtitle text. There is no dedicated editing
model slot in the authorized model vocabulary.

R2c explicitly maps editing analysis to **`planning.storyboard`**: it is the
existing configurable text slot whose responsibility covers Shot order, pacing
and storyboard-level sequence decisions. No hidden “Director default” or new
unconfigurable slot is introduced.

## Outcome

- Route both instructed and proactive Editing suggestions through the audited
  R2a text bridge and persist/link one DirectorTurn and one existing proposal.
- Add request-key idempotency and invocation evidence to the Editing API/UI.
- Send the sanitized real Timeline, including subtitle text, to the model.
- Extend the narrow typed plan with `set_clip_subtitle`; keep reorder and duration
  operations. Apply changes only to the local draft, then require the existing
  explicit Timeline save. No media regeneration is submitted.
- Keep the deterministic transport only as an explicitly injected fixture.

## Owned paths

- `backend/app/director/editing_suggestion.py`
- `backend/app/director/text_transport.py` only if shared finalization needs a
  bounded extension
- `backend/app/editing/proposal_plan.py`
- `backend/app/director/proposal_commands.py`
- `backend/app/api/v1/editing.py`
- focused backend tests
- `frontend/src/features/editing/api.ts`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- generated OpenAPI types and focused frontend unit/E2E fixtures
- this contract and Goal status

## Invariants

- Editing model output is a strict allow-listed Timeline plan. It cannot carry
  Artifact, production lineage, Provider/Runtime, arbitrary patch/path, SQL or
  replacement JSON.
- Suggestion generation/persistence does not modify EditSession.timeline or
  version, create NodeRun/Artifact, or call a media Provider.
- Applying a shown operation affects only the current in-browser draft. The
  existing explicit save and optimistic version check remain authoritative.
- Text-model failure, unknown submission, invalid output and stale Timeline are
  visible failures; none silently becomes a deterministic suggestion.
- Same request key/context has one text call, one turn and one proposal.

## Acceptance

1. A configured `planning.storyboard` model receives exact ordered clip ids,
   durations and subtitles and returns a valid context-related plan with matching
   turn/model evidence.
2. Reorder, duration and subtitle operations preview and apply to draft; only an
   explicit save increments EditSession version. Subtitle changes create no
   media execution or production record.
3. Same-key replay creates neither another model call nor another proposal;
   changed context conflicts.
4. Cross-project/session, stale-before, stale-after, invalid target, malicious
   field, unavailable model and second-invalid repair fail closed.
5. Full relevant backend, PostgreSQL, frontend and E2E gates pass.

## Result

- Instructed and proactive Editing suggestions now resolve the explicitly
  documented `planning.storyboard` slot and run through the audited R2a text
  bridge. The production default never selects the deterministic fixture.
- The model context contains ordered clip ids, Shot ids, durations, subtitles
  and sanitized Timeline metadata. Artifact ids, production lineage and
  Provider/Runtime fields are excluded. Controlled model evidence proves the
  returned plan is tied to that context and one persisted turn/proposal/item.
- `set_clip_subtitle` joins the existing strict reorder/duration union. Unknown
  targets and malicious fields fail closed; empty subtitle retains the explicit
  “subtitle off” meaning and CRLF is normalized without removing line breaks.
- Same-key replay has one model call and one proposal. A concurrent EditSession
  version change marks the real text turn `stale`; missing configuration and
  invalid plans remain durable manual-safe failures.
- The UI returns a stable request key, shows exact model/turn identity and
  applies reorder, duration or multiline subtitle only to the browser draft.
  Subtitle editing now uses a multiline control. Only the pre-existing explicit
  Timeline save advances the session version; focused assertions observe no
  media generation/repair request.
- Same-candidate backend Gate: directory/canonical checks, Ruff, MyPy `239`
  source files, `920` unit tests, migration drift check, `21` PostgreSQL
  integration tests and OpenAPI export all PASS.
- Same-candidate frontend Gate: API generation check, Prettier, ESLint, native
  TypeScript 7 and production build PASS; Vitest `28` files / `142` tests PASS;
  Playwright `19` PASS.
- SHA-256 comparison confirms all 14 verified runtime/API/test files match the
  integration and isolated quality worktrees; `git diff --check` PASS. The
  verification used unchanged locked dependency images and made no paid or
  external Provider request.

## Next

R3 audits and closes the effective creative-intent chain: explicit user values,
accepted proposals, project overrides, Skills/style/shot-language versions and
model capability must match the actual downstream execution request.
