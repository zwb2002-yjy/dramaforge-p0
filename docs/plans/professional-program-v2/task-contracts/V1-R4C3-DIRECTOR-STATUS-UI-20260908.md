# V1 R4c3 — Refresh-safe Director status and explicit controls

**Task:** `v1-r4c3-director-status-ui-20260908`\
**Parent:** G3 / G4 / G6 / R4c\
**Status:** IMPLEMENTED / VERIFIED (immutable-source pass pending)\
**Baseline:** `dev@057a13b`

## Authority and current drift

The registered Owner revision requires the Director surface to show the current
understanding, one focused suggestion, its difference/reason and the next
confirmation point. Server facts must survive refresh and browser closure;
React state must not become a second execution truth. R4c1 supplies durable
detached Shot decisions and R4c2 supplies actual Workbench receipts/business
checkpoints, but the current Shot panel keeps every result in component state,
drops it on refresh and discards/applies without calling those decision APIs.

The existing Workbench production surface already previews the frozen model,
reference delivery and exact/approximate/unsupported result. Approximation has
an explicit re-preview and identity comparison before dispatch. This task must
preserve and test that boundary, not replace it with Director UI state.

## Outcome

- Project the newest persisted Shot Director turns through React Query, with a
  bounded poll only while a server turn is active. A reload restores the exact
  persisted suggestion, model evidence, state, waiting reason and typed next
  checkpoint without creating a text/media request.
- Bind detached Shot suggestion/recommendation controls to the exact turn and
  revision. Whole/partial acceptance and rejection are saved through the R4c1
  decision API before changing the local draft; duplicate delivery is safe.
- Provide explicit stop and reconcile controls for eligible turns. Reconcile
  only asks the server to re-read canonical facts. Terminal/stale turns are
  visibly non-applicable and network loss is shown as unsynchronised state, not
  rewritten as a business failure.
- Keep local draft + explicit design Save, Candidate -> Formal, and paid media
  dispatch as their existing separate gates. Director controls never dispatch
  production or select Formal media.

## Owned paths

- `frontend/src/features/director/api.ts`
- `frontend/src/features/director/suggestion-types.ts`
- `frontend/src/features/director/DirectorTurnStatus.tsx` (new)
- `frontend/src/features/director/ShotDirectorSuggestionPanel.tsx`
- `frontend/src/lib/queryKeys.ts`
- `backend/app/api/v1/director.py` (existing repair-count read projection only)
- `frontend/src/shared/api/generated.ts`
- focused frontend unit/E2E tests and existing production-plan regressions
- this contract and the V1 Goal status

## Non-scope and authorization

No backend business/database-schema change, automatic Proposal apply, automatic Save,
Formal selection, paid dispatch, Provider call, production deployment/write,
global install or Owner merge. Editing retains its existing typed Proposal and
explicit timeline Save boundary; R5/R6 own runtime/final-film evidence.

## Acceptance / verification

1. Reload/list recovery restores the exact persisted Shot output and current
   server checkpoint; list/read controls do not call text or media endpoints.
2. Apply/reject submits the exact turn revision and accepted operation indices.
   API failure changes no draft; exact replay is harmless; stale/cancelled/
   failed turns cannot be applied.
3. Stop and resume use the current revision, invalidate the same scoped Query,
   and expose server reasons/actions. Polling runs only for active states and
   network errors render a sync warning without fabricating `failed`.
4. Switching Shots never carries output or decisions between scopes. Dirty and
   Shot-version guards continue to block unsafe request/application.
5. Existing execution-plan tests prove exact/approximate/unsupported display,
   explicit approximation confirmation and frozen preview identity before paid
   dispatch; Director changes do not weaken them.
6. Focused tests, full frontend static/unit/build/Playwright and relevant
   generated/backend gates pass on the committed candidate. Preserve the known
   root-ledger registration restriction and do not claim R5-R8 completion.

## Implementation and development verification

- The selected-Shot Director sheet now reads the owner-scoped turn list and
  polls every four seconds only while at least one persisted turn is active.
  It reconstructs the allow-listed Shot suggestion/recommendation from the
  stored output snapshot and invocation identity; component state is never
  treated as recovery truth.
- The status card shows current understanding, focused suggestion, wait reason,
  bounded step/revision and the stored typed next action. Explicit stop and
  reconcile controls send the current revision. Network failure displays
  `状态待同步` and cannot synthesize a failed turn.
- Detached decisions first re-read the exact turn, then persist whole/partial
  acceptance or rejection. Draft mutation happens only after a successful
  decision response. Poll-observed stale/cancelled/failed turns immediately
  disable the local preview. Accepted output remains re-playable after refresh,
  while exact server replay stays idempotent.
- `schema_repair_count` was already durable but absent from the secret-free
  read projection. It is now included so rehydrated evidence does not invent a
  zero repair count; no migration or business-state change was needed.
- The existing Workbench production component remains the only dispatch path.
  Its focused regressions cover exact/approximate/unsupported, explicit
  approximation confirmation and re-preview identity equality before submit.
- Development gates: Ruff PASS; MyPy 242 app files PASS; backend unit 977 PASS;
  PostgreSQL integration 23 PASS (the five separately gated real-LiteLLM cases
  remain intentionally skipped in this PG command); generated API consistency,
  Prettier, ESLint, native TypeScript and production build PASS; frontend unit
  150 PASS; Playwright 19 PASS. A first backend run inherited a SQLite URL and
  correctly failed the default-PostgreSQL settings assertion; rerun without
  that harness override passed. A first full frontend run had one existing
  WorkstationShell timeout; its isolated 14/14 and complete rerun 150/150 passed.
- No paid Provider request, production write/deployment or automatic Formal/
  media action occurred. Root-ledger registration remains unavailable because
  the preserved Owner input files make the root checkout dirty; no event is
  forged and those files remain untouched.
