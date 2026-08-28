# LEGACY_INVENTORY

**Branch:** `dev` · **Freeze HEAD:** `237741f37f84cfbe71b37177772ca50e2d20646c` · **Alembic head:** `20260827_0049` · **Date:** 2026-08-28

> **Purpose.** Freeze every LEGACY / COMPAT / PLACEHOLDER / EXPERIMENTAL component and the Phase 8 deletion conditions (方案 §24). Nothing here is removed now — this is the audit that **authorizes** later removal. Removal happens only after the first real production loop passes (Phase 8), and the §24.1 multi-condition gate for each component is recorded.

---

## 1. Definitions (方案 §12.3)

- **CANONICAL** — formal product chain.
- **COMPAT** — keeps old data/calls working, but must not grow new features.
- **LEGACY** — read-only or pending deletion.
- **PLACEHOLDER** — a stub only, not a realized feature.
- **EXPERIMENTAL** — future capability, must not affect the first real film.

No component may carry an `UNKNOWN` / "待决定" / "以后看" / "可能使用" classification.

## 2. Backend legacy / compat / placeholder / experimental

| Item | Path | Classification | Evidence | Phase 8 condition state |
|---|---|---|---|---|
| `creation` package (Brief/Plan/Authorization) | `backend/app/creation/` | LEGACY/COMPAT | Gates `require_legacy_execution_allowed` / `require_recovery_only_project` (`director/legacy_guard.py`). Only the legacy-recovery materialization path. | No formal UI/API consumer on the Canonical chain; gate blocks new use |
| `creation.py` recovery route (`/creation/*`, `/brief/{rev}/confirm`, `/plans/{id}/confirm`) | `backend/app/api/v1/creation.py` | LEGACY/COMPAT | Recovery-only gate | Same |
| `director` 0018 Workflow block (11 tables) | `backend/app/director/models.py` (tables from `20260813_0018`) | LEGACY-adjacent | Older controlled-Director + `production_batch` + budget system; superseded by Phase 7 Director Assist (`director_threads`/`director_proposals`) | Full table list in DATA_MODEL_INVENTORY §4.3. No removal migration yet |
| `features/director/` stage UIs | `frontend/src/features/director/` (`CreativeStage`, `ShootingStage`, `TrialStage`, `ProductionStage`, `DirectorBoard2D`, `ProposalItem`, `ProposalPreview`) | COMPAT | Only `api.ts`/`stageMap.ts`/`types.ts` are imported (legacy overview inspector). Stage UIs have no route consumer | UI orphaned; `api/stageMap/types` still consumed — do not delete until `routes/projects.$projectId.tsx` inspector is migrated |
| `lib/quickWorkflow.ts` | `frontend/src/lib/quickWorkflow.ts` | LEGACY | Imported **only** by `frontend/tests/unit/quickWorkflow.test.ts`; no `src` importer | Test-only. Verify `test_phase10_*` still references it before removal |
| `lib/artifactStage.tsx`, `lib/useStageArtifact.ts`, `lib/projectMedia.ts`, `lib/queryKeys.ts` | `frontend/src/lib/` | LEGACY | Orphaned — no `src` importer | Dead code, safe to remove once confirmed no test dependency |
| `components/shared/ManifestOptionControls.tsx` | `frontend/src/components/shared/` | COMPAT/LEGACY | No route consumer (only unwired `model-controls`) | Orphaned |
| `components/assets/AssetMentionInput.tsx` | `frontend/src/components/assets/` | LEGACY | Orphaned (the used picker is `AssetReferencePicker`) | Orphaned |
| `execution/pipeline.py` (FirstFramePipeline) | `backend/app/execution/pipeline.py` | LEGACY | Explicit "not the S2 product path (no Outbox/Arq)"; in-process fake adapters | Test/fixture helper |
| `execution/golden_path.py` | `backend/app/execution/golden_path.py` | COMPAT | Test/fixture driver (fake adapters) | Test-only |
| `providers/adapters_v2.py` | `backend/app/providers/adapters_v2.py` | LEGACY_COMPAT | A+B ModelAdapter bridge; explicit `LEGACY_COMPAT` marker | Test/back-compat |
| `providers/router.py` (CapabilityRouter) + `contracts/` + `intent_bridge.py` | `backend/app/providers/` | COMPAT | V3 text/generation router, additive; default text path is the legacy OpenAI adapter (`text_v3_router_enabled=False`) | Additive, not removed |
| `providers/litellm_gateway/` | `backend/app/providers/litellm_gateway/` | EXPERIMENTAL | Flag `text_v3_router_enabled` off | Not on media path |
| `legacy adapter path` inside `product_path.py` | `backend/app/execution/product_path.py` | COMPAT | Gated by `provider_unified_path_enabled=False` / `provider_unified_shadow` | Keep until unified path default-on |
| `project_provider_bindings` (system-default/legacy fallback) | `backend/app/providers/models.py` + `providers/models.py` | COMPAT | `selection_strategy="explicit_binding"` only; `ExecutionModelResolver` final `system_default` source | Fallback only when no profile slot declared; labeled |
| `consistency` package | `backend/app/consistency/` | PLACEHOLDER/EXPERIMENTAL | Pure functions consumed by execution, no dedicated router | Shell, not a feature |
| `editing` package | `backend/app/editing/` | PLACEHOLDER/EXPERIMENTAL | `edit_sessions` table + model, but **no router wired** | Phase 9; not yet product-reachable |
| `features/experiments/ExperimentCompare.tsx` | `frontend/src/features/experiments/` | EXPERIMENTAL | Presentational only, no importer | Not product-reachable |
| `features/model-controls/` | `frontend/src/features/model-controls/` | EXPERIMENTAL | `index.ts` exports, no route imports | Not product-reachable |
| `features/review/` | `frontend/src/features/review/` | EXPERIMENTAL | `index.ts` exports, no importers | Not product-reachable (review is delivered via `delivery` package + `api/v1/review.py`, not these components) |

## 3. Frontend placeholders (方案 §2 / §16.3)

Empty `.gitkeep`-only dirs (current app surface does not consume any of these):

- `frontend/src/features/audit/`
- `frontend/src/features/creation/`
- `frontend/src/features/delivery/`
- `frontend/src/features/projects/` (note: `features/assets` and `features/production` have real files + a `.gitkeep`; `features/projects` is **only** `.gitkeep`)
- `frontend/src/features/storyboard/`
- `frontend/src/components/sse/`

Plus `.gitkeep` alongside real files in: `features/assets`, `features/production`, `features/review`, `components/shared`, `components/ui`, `hooks/`.

Also: `frontend/src/types/api.ts` + `types/openapi.json` — `openapi-typescript` generated output that is **not imported** by any `src` file. This is an **unwired generated artifact** (`PLACEHOLDER`), the Phase 2 target is to wire it via `npm run api:generate`.

## 4. Frontend legacy surface (Quick / migration)

| Item | Path | Classification | Notes |
|---|---|---|---|
| `/projects/$projectId/quick` route | `frontend/src/routes/projects.$projectId.quick.tsx` | LEGACY | Quick retire notice page ("Quick 模式已退役"); e2e asserts the app does **not** redirect to it |
| Quick mode column | `projects.experience_mode` / `user_project_preferences` | LEGACY/COMPAT | `ExperienceMode.QUICK` = "retired legacy experience"; `is_recovery_only` |
| `creation-preview` mock UI | `frontend/src/features/creation-preview/{QuickCreationPreview,QuickCreationShell,components.tsx,mockData.ts,types.ts,quick-creation-preview.css}` | COMPAT | Mock/design-preview only, served at `/design-preview/product`. **The two real shells (`ProjectWorkspaceShell`, `ProjectLobbyShell`) are CANONICAL** and must be *migrated* (Phase 1), not deleted |
| `creation-preview` real nav shells | `frontend/src/features/creation-preview/ProjectWorkspaceShell.tsx`, `ProjectLobbyShell.tsx` | CANONICAL (migration target) | Move to `components/workstation/` / `app/layouts/` in Phase 1; formal business code must stop importing `creation-preview` afterwards |

## 5. Phase 8 removal gate (方案 §24.1)

A LEGACY component may be deleted **only when ALL** hold:

```text
[ ] No formal UI consumes it
[ ] No Canonical API consumes it
[ ] No new DB writes
[ ] No runtime dependency
[ ] No test dependency
[ ] Historic data migrated (for DB tables)
```

Prioritized cleanup order (方案 §24.2):
`Quick frontend business code` → `quickWorkflow.ts` → `creation-preview naming` → `旧 Director 产品入口` → `旧 Workflow 产品状态映射` → `empty .gitkeep feature` → `no-consumer API` → `no-consumer Service` → `old hand-written DTO` → `transition alias`.

DB deletion must follow (方案 §24.3): stop new writes → read-only → confirm 0 consumer → migrate data → observe one release → Alembic drop. **No direct `DROP`.**

## 6. Freeze statement

At this HEAD, the **legacy surface is bounded and enumerated** — the 0018 Director block, the `creation` recovery package, `quickWorkflow.ts`, the orphaned lib/component files, the V3-COMPAT provider layer, and the placeholder feature dirs. None are removed now; they are recorded so Phase 8 removal and Phase 1–2 migration have a precise, verified target list.
