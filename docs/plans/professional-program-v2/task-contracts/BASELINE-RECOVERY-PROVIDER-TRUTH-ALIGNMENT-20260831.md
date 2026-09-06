# Task: Baseline Recovery + Provider Truth Alignment (2026-08-31)

## Status

- **State:** COMPLETE (bounded recovery; live schema drift deferred)
- **Program position:** Follow-up to the completed MS5 identity and Phase 4
  reconciliation contracts. This contract does not reopen those gates.
- **Scope:** Restore the current strict-typing baseline, route newly queued
  Professional Workbench media runs through the frozen unified Provider path,
  and make the frontend API contract check a required CI step.

## Read first

- [`../README.md`](../README.md)
- [`MS1-R-AND-MS1-C-EXECUTION-MODEL-RESOLUTION.md`](MS1-R-AND-MS1-C-EXECUTION-MODEL-RESOLUTION.md)
- [`MS5-R-CONCRETE-MODEL-RUNTIME-RESOLUTION.md`](MS5-R-CONCRETE-MODEL-RUNTIME-RESOLUTION.md)
- [`MS5-IDENTITY-B-PROVIDER-CONNECTION-REVISION.md`](MS5-IDENTITY-B-PROVIDER-CONNECTION-REVISION.md)
- [`MS5-IDENTITY-C-EXECUTION-IDENTITY-FREEZE.md`](MS5-IDENTITY-C-EXECUTION-IDENTITY-FREEZE.md)
- [`RECONCILIATION-20260829-CANONICAL-EXECUTION-UI.md`](RECONCILIATION-20260829-CANONICAL-EXECUTION-UI.md)

## Current evidence

- `backend/.venv/Scripts/python.exe -m mypy app` reported 25 errors in
  `asset_card_service.py`, `api/v1/scenes.py`, and `api/v1/workbench.py`.
- P4 Workbench `NodeRun` snapshots contained a frozen workbench plan, but the
  worker dispatch predicate did not recognize that plan when the unified-path
  feature flag was off; the run could fall through to legacy Flux/Kling
  media wrappers.
- `.github/workflows/ci.yml` installed the frontend and ran lint/typecheck/tests
  but did not require `npm run api:check` in its `frontend` job.

## Target and boundaries

- Repair the 25 real typing errors without `# type: ignore`, strictness
  weakening, or widening application data to `Any`.
- Persist connection revision identity with Workbench plans and consume the
  frozen `ExecutionModelResolution`, `ProviderConnectionRevision`,
  `ProviderRuntimeResolver`, and `ProviderPluginRegistry` path before any
  Provider submission. Keep legacy wrappers available only for historical
  compatibility runs.
- Unknown, missing, disabled, or mismatched Professional Provider identity
  fails closed before a Provider request.
- Require `npm run api:check` in the frontend CI working directory and cover
  the workflow contract with a focused test.
- Do not make real or paid Provider calls. Do not add pricing architecture,
  delete `materialization_operations`, rewrite migration history, or apply an
  automatically generated migration.

## Implementation evidence

- The three mypy-error modules now use explicit role typing and Pydantic
  boundary validation; `mypy app` reports success for 252 source files.
- Workbench snapshots carry a professional-unified marker, the typed model
  resolution with connection/credential revision ids, and compatibility
  selection evidence. The worker builds its runtime through the frozen
  revision resolver and never calls the legacy Flux/Kling factories for that
  path. A focused fake-runtime test keeps the feature flag off and makes both
  legacy factories fail if touched.
- `ci.yml` frontend now runs `npm run api:check` after `npm ci`; a focused
  workflow contract test asserts the job and working directory.

## Alembic drift disposition (read-only / no-guess)

`alembic --raiseerr check` was run against the local PostgreSQL instance using
the local `dramaforge` credentials. It exited non-zero with historical
autogenerate differences, including the preserved
`materialization_operations` table/index, JSONB-versus-JSON declarations,
legacy index/FK/unique names, and the additive ProviderOperation revision
index shape. These findings are classified as metadata/schema-history drift,
not as an authorized migration request. No `alembic revision --autogenerate`,
`upgrade`, schema mutation, volume reset, or data update was performed.

Resolution is deferred to a separately authorized migration contract with
explicit schema authority; this task makes no guesses and preserves the
existing migration chain.

## Verification gate

- Focused Workbench/unified, identity, runtime-resolution, API, and CI contract
  tests pass.
- Full backend unit run: 967 passed; 2 directory-compliance failures are
  caused only by the pre-existing unregistered root `codex-with-chatgpt`
  workspace entry.
- `ruff check app tests alembic/versions`, `mypy app`, and `git diff --check`
  pass.
- No real or paid Provider request was made.
