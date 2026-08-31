# Task: 2026-08-29 Canonical Execution / Migration / UI Reconciliation

## Status

- **State:** COMPLETE (bounded reconciliation; live schema-drift follow-up recorded)
- **Program order:** bounded reconciliation after the recorded Phase 5 work; it does not reopen or replace MS5-B/C, P5, P6, P9, or P10 gates.
- **Task boundary:** Reconcile audit findings against the current worktree, close only confirmed execution-identity, Alembic metadata, transport-contract, and canonical UI drift, and record evidence for findings that are already fixed or remain outside this bounded scope.

## Read first

- `../README.md`
- `../01-DramaForge_专业版产品与开发最终方案_完整交互版.md` (professional workbench, review, editing boundaries)
- `../02-DRAMAFORGE_PRO_DESIGN.md` (execution facts, routes, migrations, UI boundaries)
- `../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` (P5/P6/P9/P10 task order and gates)
- `../04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md` (concrete binding/runtime identity)
- `../05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md` (MS5 runtime and golden checks)
- `../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` (identity/revision/fail-closed rules)
- `../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` (MS5 identity, P10 UI/model audit, verification)
- `MS5-IDENTITY-B-PROVIDER-CONNECTION-REVISION.md`
- `MS5-IDENTITY-C-EXECUTION-IDENTITY-FREEZE.md`
- `P5-GATE.md`, `P6-GATE.md`, `P6-MANUAL-REPAIR.md`, `P6-REVIEW-UI.md`, `P9-OPENCUT-EDITING.md`, `P10-UI-CONSOLIDATION.md`, `P10-MIGRATION-NOGUESS-AUDIT.md`, `P10-RLS-MODELRES-AUDIT.md`

## Current Evidence / Drift (2026-08-29)

- Existing Phase 5 worktree changes are user-owned and preserved: `backend/app/execution/shot_review.py`, `backend/tests/unit/test_product_path_shipped.py`, `backend/tests/integration/test_phase5_restart_recovery_pg.py`, `docs/architecture/PHASE_GATE.md`, and `docs/reviews/PHASE5_MERGE_GATE_AUTONOMOUS_RUN_REPORT.md`.
- MS5-B/C code and tests already exist, including `ExecutionIdentitySnapshot`, connection revisions, and frozen resume checks. Re-audit found a remaining race/authority gap: a new unified run can build its runtime from mutable `ProviderConnection` state and only then read the latest revision; a frozen rejected retry also does not consistently carry the already-frozen revision through the request evidence path.
- `backend/alembic/env.py` assigns `Base.metadata` without importing `app.shared.model_registry.load_all_models()`. A fresh migration process therefore starts with an empty metadata registry even though workers/tests load all models.
- `frontend/src/lib/api.ts` duplicates generated transport DTOs for User, Workspace, provider probes/bindings, project/provider bindings, Project, creation responses, and Export. `features/assets/api.ts` duplicates generated asset/reference DTOs. `features/shots/api.ts` returns `Record<string, unknown>` for a typed `ShotWorkbenchRead`; `features/production/workflow-api.ts` hand-maintains the workflow read model while its backend response is opaque in OpenAPI.
- `executeNodeRun()` in `frontend/src/lib/api.ts` targets `/projects/{project_id}/node-runs/{node_run_id}/execute`; no backend route or consumer exists. It is safe to remove after a repository-wide consumer check.
- `frontend/src/routes/projects.$projectId.tsx` still imports and requests retired `/director/workspace-snapshot` data for the formal project root. Canonical Project / workspace-state / Scene data is available.
- `/review` has no route. `/edit` exists but is a Phase 1 placeholder, while the P6/P9 contracts are recorded complete. Existing review widgets and the OpenCut manifest endpoint are the available canonical seams; no second production truth may be introduced.
- Migration history is additive and must not drop `materialization_operations`; no authority/chain evidence authorizes that destructive change.

## Objective

1. Make the unified Professional provider request consume a runtime reconstructed from the exact frozen connection revision before first network traffic, including retries/resubmission evidence.
2. Load every ORM model in standalone Alembic processes and add a deterministic metadata/import regression check.
3. Make the listed frontend transport clients consume generated OpenAPI types, remove the confirmed dead execute endpoint client, and preserve typed shot/asset/workflow responses.
4. Remove retired Director snapshot usage from the canonical project root and provide minimal `/review` and `/edit` surfaces using existing API/component seams; record any missing save/export HTTP seam as a blocker rather than inventing one.

## Owned paths

- `backend/alembic/env.py`
- `backend/app/execution/product_path.py`
- `backend/app/providers/runtime.py`
- `backend/app/providers/model_resolution.py`
- `backend/app/director/workflows/workflow_read_models.py`
- `backend/app/api/v1/workflow_overview.py`
- `backend/tests/unit/test_execution_identity.py`
- `backend/tests/unit/test_unified_path.py`
- `backend/tests/unit/test_alembic_metadata.py`
- `frontend/src/lib/api.ts`
- `frontend/src/features/assets/api.ts`
- `frontend/src/features/shots/api.ts`
- `frontend/src/features/production/workflow-api.ts`
- `frontend/src/routes/projects.$projectId.tsx`
- `frontend/src/routes/projects.$projectId.review.tsx`
- `frontend/src/routes/projects.$projectId.edit.tsx`
- `frontend/src/features/review/ReviewWorkspace.tsx`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/tests/unit/ProjectRoot.test.tsx`
- `frontend/tests/unit/ReviewWorkspace.test.tsx`
- `frontend/tests/unit/EditingWorkspace.test.tsx`
- this Task Contract

## Explicitly out of scope

- Existing Phase 5 in-flight files listed above, except for compatible test/evidence additions if required.
- New runtime/worker/generation abstractions, Provider calls, paid traffic, or changes to legacy compatibility semantics.
- Destructive migrations or dropping `materialization_operations`.
- Rebuilding OpenCut or inventing edit-session persistence/API contracts not present in the current backend.
- Broad rewrite of the Director feature or old `/quick` behavior.

## Acceptance / Verification

- Unified new and rejected-retry paths persist one identity/revision and build runtime from frozen revision values before submit; missing/mismatched identity fails closed with zero Provider calls.
- `Base.metadata` is non-empty in a fresh `alembic.env` import and includes all registered ORM tables; metadata/migration/OpenAPI checks are runnable without real Providers.
- `npm run api:check`, TypeScript, lint, unit tests, backend ruff/mypy/unit tests pass (PG only when enabled/reachable).
- Canonical root has no Director snapshot request; `/review` and `/edit` render only existing project/scene/workbench/review/OpenCut data. Any unavailable persistence operation is explicitly surfaced as a bounded blocker.

## Finding disposition ledger

The implementation updates this section with `fixed`, `already-fixed`, or `deferred` and evidence/contract reason for each audit finding.

## Finding disposition (2026-08-29)

| Finding | Disposition | Evidence / reason |
|---|---|---|
| Dispatch/runtime could drift from the selected connection or credential revision before the first Provider request | **fixed** | `backend/app/execution/product_path.py` captures the current revision for new work, rebuilds the runtime through `ProviderRuntimeResolver.resolve_runtime_for_identity()` before `submission_started`, and reuses the frozen revision on rejected retries. Existing unified tests cover rev1 resume after endpoint/credential rev2 and now assert the first-submit runtime is `FrozenProviderConnection`. |
| Alembic fresh process has empty `Base.metadata` | **fixed** | `backend/alembic/env.py` calls `load_all_models()` before assigning `target_metadata`; registry now includes every ORM module, including editing, director proposal, and production model-profile ORM. `tests/unit/test_alembic_metadata.py` covers required tables; offline `alembic upgrade head --sql` passes. |
| Handwritten transport DTOs in `lib/api.ts` | **fixed** | Listed User/Workspace/Provider probe/binding/project binding/Project/creation/export DTOs now alias `shared/api/generated.ts`; compatibility-only fixture fields are explicitly marked deprecated. `ReviewAnnotationRead` and `OpenCutManifestRead` also use generated schemas. |
| Assets/reference feature DTO duplication | **fixed** | `features/assets/api.ts` uses generated Asset/Tag/Version/Card/Binding/ResolvedReference schemas. |
| Typed Shot Workbench response was widened to `Record` | **fixed** | `features/shots/api.ts::fetchShotWorkbench` returns generated `ShotWorkbenchRead`. |
| Dead `POST /node-runs/{node_run_id}/execute` frontend client | **fixed** | Repository-wide consumer search found no use; `executeNodeRun` was removed. No backend route exists. |
| Formal project root probes retired Director `/workspace-snapshot` | **fixed** | `projects.$projectId.tsx` now reads canonical `GET /projects/{project_id}` and workspace state only; no import or query of `fetchDirectorWorkspace`. |
| `/review` route missing despite P6 completion | **fixed (minimal)** | Added route and `ReviewWorkspace` using existing `ShotWorkbenchRead`, ReviewAnnotation API, `MediaReviewCanvas`, and `VideoReviewTimeline`; no second production fact store. |
| `/edit` remained a placeholder despite P9 completion | **deferred with explicit blocker** | Added `EditingWorkspace` consuming the existing canonical OpenCut manifest and showing production lineage. Current backend exposes no save/load/export HTTP routes for the completed `EditingAdapter`; no fake local persistence or new transport contract was introduced. |
| `assets/workflow-api` broad hand-written workflow DTO drift | **deferred with contract reason** | Generated OpenAPI currently exposes the workflow overview payload as an opaque object. Broadly changing that contract would expand this reconciliation; no behavior was changed. |
| `materialization_operations` destructive migration concern | **already-fixed / preserved** | No drop or destructive migration was added; additive migration chain remains untouched. |
| Live Alembic autogenerate parity | **deferred with explicit no-guess boundary** | After rebuilding the current worktree, container-local `alembic current` reached `20260827_0049 (head)`, but read-only `alembic check` reported historical ORM/schema differences (including the preserved `materialization_operations` table, JSONB/JSON type declarations, and migration-defined index/FK names absent from ORM metadata). This contract does not authorize a broad or destructive normalization migration; no generated operations were applied. |
| Existing Phase 5 worktree changes | **already-fixed / preserved** | All five user-owned files remain unchanged by this reconciliation except the compatible identity assertion in the existing unified test. |

## Verification record

- Backend: focused identity/revision/workbench/metadata/product-path tests `39 passed, 1 warning`; product-path shipped tests `14 passed, 1 warning`; identity/retry regression tests `2 passed, 1 warning`.
- Backend static: `ruff check app tests alembic/versions` passed. `mypy app` remains blocked by 25 pre-existing strict-typing errors in `app/assets/asset_card_service.py`, `app/api/v1/workbench.py`, and `app/api/v1/scenes.py`; these files are outside the bounded reconciliation and were not weakened or rewritten.
- Migration/runtime follow-up: rebuilt API, dispatcher, default/heavy workers, and frontend from the current worktree without clearing volumes. Container-local live `alembic current` reports `20260827_0049 (head)` and the database contains 71 public tables. Read-only `alembic check` runs successfully against PostgreSQL but exits non-zero because it detects the historical ORM/schema differences recorded above; no generated operations were applied and no database row or schema object was modified by the check.
- Runtime contract: all rebuilt services are healthy; the running OpenAPI exposes 146 paths, including script and creative-capability routes, and does not expose the removed `node-runs/{node_run_id}/execute` route. Browser checks loaded production, `/review`, and `/edit` with no console errors using an existing authenticated local test session.
- Frontend: `npm run typecheck`, `npm run lint` (2 existing warnings, 0 errors), `npm test -- --run` (`95 passed`), `npm run build`, and `npm run api:check` passed.
- No real/paid Provider call was made. Docker compose rebuild and live PG integration were not run because the local runtime/database authority and credentials were not safely available; existing PG integration remains environment-gated.
