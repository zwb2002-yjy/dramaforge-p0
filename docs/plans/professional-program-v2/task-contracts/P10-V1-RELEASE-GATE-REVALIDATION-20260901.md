# Task: P10 V1 Release Gate Revalidation — 2026-09-01

## Status

- **Task id:** `p10-v1-release-gate-revalidation-20260901`
- **Execution state:** COMPLETE (current-candidate evidence and report update complete)
- **Release verdict:** **PASS**
- **Current candidate:** `dev` at `66eb4d28a352dc093e1f8a7c3d733601d13a9f7c`
- **Candidate commit date:** `2026-09-01T20:16:04+08:00`
- **Scope:** Revalidate the Phase 10 V1 Release Gate in 03 §95 against the exact
  current committed source, including the explicitly authorized real Provider
  Golden run. This contract records evidence and an honest PASS/FAIL/BLOCKED
  decision; it authorizes no production code changes.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §95
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §23
- [`P10-V1-RELEASE-GATE.md`](P10-V1-RELEASE-GATE.md)
- [`P10-07-EDITING-E2E-RECONCILIATION.md`](P10-07-EDITING-E2E-RECONCILIATION.md)
- [`../../../reviews/V1-RELEASE-GATE-REPORT.md`](../../../reviews/V1-RELEASE-GATE-REPORT.md)

## Retained prior current revalidation evidence

The preceding current-candidate revalidation remains retained in the release
report as candidate `78f2df44eaa43781e12738e3f29911be34e336b6`. That run used a
clean detached worktree and migration `20260901_0050`, passed the then-run
backend/PG/frontend/Playwright checks, but honestly recorded four existing
`scripts/` ruff findings, a drifted Compose stack, no current paid-call
authorization, and an overall `BLOCKED` verdict. This superseding run does not
rewrite or delete those earlier facts.

## Current evidence / drift

- The current candidate is the actual `dev` HEAD `66eb4d28a352dc093e1f8a7c3d733601d13a9f7c`.
  A detached clean worktree at
  `D:\dramaforge\.worktrees\p10-v1-golden-20260901` was created directly from
  that commit. Its source status was empty before evidence generation; final
  status contains only the three allowed evidence-document changes (report,
  revalidation contract, and Golden JSON). No application, test,
  script, migration, UI, Provider, Runtime, Worker, frontend, or infrastructure
  source was changed.
- The root `D:\dramaforge` was not modified. Its pre-existing
  `docs/reviews/V1-RELEASE-GATE-REPORT.md`,
  `docs/plans/professional-program-v2/task-contracts/P10-V1-RELEASE-GATE-REVALIDATION-20260901.md`,
  and untracked `codex-with-chatgpt/` remain outside the candidate worktree.
- Candidate backend/frontend images were rebuilt with unique local tags and
  OCI/runtime source identity `66eb4d28…`. API, dispatcher, both workers,
  frontend, Postgres, Redis, MinIO, and LiteLLM ran in isolated Compose project
  `p10-v1-golden-20260901`; all were healthy. API `/health` and LiteLLM
  readiness returned 200, and frontend gateway returned 200.
- The isolated candidate database was migrated to `20260901_0050 (head)`;
  `alembic heads`, `alembic check`, and `alembic current` passed. The runtime
  role was verified `LOGIN=true`, `BYPASSRLS=false`, `SUPERUSER=false`, with a
  configured password.
- The existing local Agnes credential was used only through the candidate
  onboarding/probe flow. It was never printed or written to evidence. The
  Agnes auth-model probe returned HTTP 200 and the keyframe/video bindings were
  `account_verified=true`.
- The user explicitly authorized the real Agnes/DeepSeek Provider scope in this
  turn. No external/provider account password was requested or used; the
  disposable local DramaForge proof account used the script's synthetic
  password and the existing local environment only.

## Allowed changes

- `docs/plans/professional-program-v2/task-contracts/P10-V1-RELEASE-GATE-REVALIDATION-20260901.md`
- `docs/reviews/V1-RELEASE-GATE-REPORT.md`
- Sanitized `docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-09-01.json` (the
  explicitly authorized current-candidate run succeeded)

## Forbidden changes

- Production, test, script, migration, UI, Provider, Runtime, Worker,
  frontend, or application code changes.
- Updating `P10-V1-RELEASE-GATE.md` or manufacturing a Golden PASS from the
  historical 2026-08-27 record.
- Committing or pushing any change as part of this revalidation.

## Verification matrix and result

All current checks were tied to the detached candidate worktree or the
isolated candidate Compose target as explicitly noted.

| Area | Command / evidence | Result |
|---|---|---|
| Source | `git rev-parse HEAD`; `git status --porcelain` before evidence | **PASS** — exact `66eb4d28…`, clean source |
| Directory | `python scripts/check_directory_compliance.py --root <candidate-worktree>` | **PASS** |
| Repository policy | `python scripts/repo_guardrails.py policy --repo-root <candidate-worktree>` | **PASS** |
| Image identity | `docker inspect` OCI revision and runtime source for API/dispatcher/workers/frontend | **PASS** — all exact `66eb4d28…` |
| Migration | Compose `migrate`; `alembic heads`; `alembic check`; `alembic current` | **PASS** — `20260901_0050 (head)` |
| Backend static | `python -m ruff check app tests alembic`; `python -m mypy app`; `python -m compileall -q backend/app scripts` | **PASS** — mypy 258 source files |
| Extended script lint | `python -m ruff check scripts` | **PASS** — all checks passed on `66eb4d2` |
| Backend unit | `python -m pytest tests/unit -q -r fE` from an exact-commit disposable archive runner | **PASS** — 1057 passed, 1 warning |
| PostgreSQL / audits | `TEST_PG_ENABLED=1 python -m pytest tests/integration -q -rs --fail-on-skip --ignore=tests/integration/test_litellm_real_proxy.py` | **PASS** — 29 passed, 1 warning; P10/P9, migration, RLS, and model-resolution audits included |
| LiteLLM runtime | `LITELLM_INTEGRATION_REQUIRED=1 python -m pytest tests/integration/test_litellm_real_proxy.py -q -rs` | **PASS** — 6 passed, 1 warning; official pinned v1.96.0 proxy with mocks |
| Runtime/model-resolution/editing focus | bounded unit command covering runtime, resolver, LiteLLM, workbench, and editing gate | **PASS** — 65 passed, 1 warning |
| Frontend lint | `npm run lint` | **PASS** — 0 errors, 2 existing Fast Refresh warnings |
| Frontend type | `npm run typecheck` | **PASS** |
| Frontend tests | `npm run test -- --reporter=verbose` | **PASS** — 32 files / 129 tests |
| API contract | `npm run api:check` with candidate backend environment | **PASS** |
| Frontend build | `npm run build` | **PASS** |
| Full Playwright | `npm run test:e2e` | **PASS** — 16 Chromium tests |
| Golden real Provider | `python scripts/prove_professional_agnes_golden.py --base-url http://127.0.0.1:18080/api/v1 --timeout 900 --out docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-09-01.json` | **PASS** — `ok=true`, `paid_provider_calls=2`, all terminal runs completed |

The combined integration command was also attempted in the disposable Linux
runner; its six LiteLLM fixture cases skipped only because that runner had no
Docker CLI. The required official LiteLLM command was then run from the host
with `LITELLM_INTEGRATION_REQUIRED=1` and passed 6/6. The candidate PG/audit
portion passed 29/29 with `--fail-on-skip`; no test was silently accepted as a
skip.

Transient harness notes: an initial unit invocation with explicit SQLite/source
environment failed four environment-sensitive tests and was discarded; the
exact-commit archive rerun with normal test defaults passed 1057/1057. On the
fresh DB, onboarding first created a second workspace while the Golden script
selects the first; the Agnes connection and auth probe were repeated in that
first workspace, and the initial Golden attempt stopped before Provider work
with `no enabled Agnes connection found`. The PG isolated-owner test temporarily
changed the candidate runtime role; candidate `database-bootstrap`, worker
restart, and candidate-only Redis flush restored the runtime before the
successful Golden rerun. Root files and containers were not changed.

## §95 evidence mapping

| §95 area | Current evidence |
|---|---|
| Architecture: one Project/Scene/Shot, Model Capability, Runtime, and Artifact truth | `test_historical_project_readable_by_new_workbench_pg`; `test_phase10_professional_resolution_no_bypass_pg`; `test_architecture_boundary_business_never_imports_concrete_providers`; `test_execution_model_resolution_round_trips_in_node_run_snapshot_pg`; `test_golden_professional_project_covers_p10_06_pg` |
| Manual production: Director Assistant off, no old Budget Gate, no Quick dependency | `professional-manual.spec.ts`; retired Quick route in `director_workflow.spec.ts`; `DirectorWorkspace.test.tsx`; `WorkstationShell.test.tsx`; `test_phase10_professional_resolution_no_bypass_pg` |
| Assets: versions, Formal/Candidate, `@资产`, historical freeze, old-version warning | `test_asset_version_promotion.py`; `AssetReferencePicker.test.tsx`; `director_workflow.spec.ts`; `test_proposal_stale_panel.py`; `test_phase10_golden_project_pg.py` |
| Models: manifest dynamic UI, local override, model swap, unsupported fail-closed | `ModelControls.test.tsx`; `professional-experiment.spec.ts`; `test_execution_model_resolution.py`; `test_execution_model_resolution_round_trips_in_node_run_snapshot_pg`; `test_execution_plan.py`; `test_reference_plan_compiler.py`; `test_creative_negative_gates.py` |
| Experiments: formal/experiment isolation and partial adoption | `professional-experiment.spec.ts`; `test_phase5_gate.py`; `test_golden_professional_project_covers_p10_06_pg` |
| Review: image Region, video time range, both V1 Repair paths | `professional-review.spec.ts`; `test_phase6_gate.py`; `test_repair_service.py`; `test_phase10_golden_project_pg.py` |
| Director agent: Proposal first, Partial apply, Stale, user manual edits win | `director-assistant.spec.ts`; `test_proposal_stale_panel.py`; `test_proposal_commands.py`; `test_phase5_gate.py`; `test_editing_director_suggestion.py` |
| Director board: 2D, rough 3D data contract, Camera/Pose/Gaze, skip path | `DirectorBoard2D.test.tsx`; `test_phase8_gate.py`; `test_golden_professional_project_covers_p10_06_pg` |
| Editing: OpenCut/Editing Adapter and Timeline cannot overwrite Production facts | P9-03A/B `test_editing_api.py` and `EditingWorkspace.test.tsx`; P9-04A/B/C/D `test_editing_proposal_commands.py`, `test_editing_director_suggestion.py`, `professional-edit.spec.ts`; `test_editing_gate.py`; migration `20260901_0050` |
| Verification: static/unit/PG/frontend/Playwright/Golden | Current matrix above: all mandatory checks pass and the sanitized Golden JSON is present |

## Golden result and verdict

The sanitized evidence file is
`docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-09-01.json` (14,011 bytes in the
repository's normalized LF checkout; SHA-256
`9404f968fef33fbc1c1ce6549a263d6d5f93eff18d6dfa44d2c3ae9bc1a9a5d5c4`). The
candidate's pre-commit CRLF copy was 14,400 bytes with SHA-256
`c1b844b7a8c70642fd7c7052f31948b3a8a4000eb44e20ab47329a435c751909`; the
content is identical after line-ending normalization.
It contains `source_commit=66eb4d28a352dc093e1f8a7c3d733601d13a9f7c`,
`dirty=false`, `ok=true`, and `paid_provider_calls=2`; the secret-value scan
found zero hits. It records two succeeded Agnes operations
(`agnes-image-2.1-flash` and `agnes-video-v2.0`), a 736×1312 PNG, a 704×1280
MP4 lasting 5.042 seconds, four Artifacts total, and an OpenCut manifest v2
with video/audio/subtitle tracks. Prompt, keyframe, identity-review, and video
runs all completed.

The JSON truthfully records both paid operations as Agnes. This particular
`prove_professional_agnes_golden.py` path did not create a DeepSeek
ProviderOperation for its prompt node, so no paid DeepSeek call is claimed; the
configured LiteLLM/DeepSeek path is covered by the required six-test official
proxy suite. The mandatory Golden invariant is `paid_provider_calls >= 1`,
satisfied by the two successful Agnes operations.

- **PASS:** all mandatory current-candidate §95 evidence, including source/DB
  identity, backend/frontend/runtime matrices, P9/P10 audits, Playwright, and
  the explicitly authorized real-provider Golden.
- **Non-blocking note:** root `codex-with-chatgpt/` remains untouched and is
  excluded from the candidate. The candidate worktree contains only the
  allowed Golden JSON after evidence generation.

**Overall current V1 Release Gate verdict: `PASS`.** No mandatory blocker
remains. The evidence was committed and pushed through protected PR #31,
squash-merged to `dev` as `6a20cdb1d2bd0abe1dacc0bc7128d07bd1ea1aa2`.

