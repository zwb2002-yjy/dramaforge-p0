# API_INVENTORY

**Branch:** `dev` · **Freeze HEAD:** `237741f37f84cfbe71b37177772ca50e2d20646c` · **Alembic head:** `20260827_0049` · **Date:** 2026-08-28

> **Purpose.** Freeze the actual HTTP API surface (`backend/app/api/v1`) and its contract status. The Api contract target (方案 §9) is: request/response schemas explicit, no Canonical `dict[str, object]`, OpenAPI is the single contract source, frontend consumes generated types. This inventory records **current** contract status and marks the gaps.

---

## 1. Aggregator

- **App assembler:** `backend/app/main.py` includes `api_router` from `backend/app/api/v1/router.py` at `prefix = cfg.api_prefix` (`/api/v1`).
- **Aggregator:** `backend/app/api/v1/router.py` defines `api_router` and includes **26 sub-routers**; `projects.py` additionally nests `workbench.router` → **27 route modules** wired into the app (the `api/v1` folder holds 27 `*_router`-defining `.py` files + `router.py`). There is no `prefix=` on any sub-router — every path is absolute under `/api/v1`.

## 2. Router tree and classification

| Path root | File | Routes (notable) | Contract status |
|---|---|---|---|
| `/auth/*`, `/workspaces*` | `auth.py` | bootstrap-status, register, login, logout, me, csrf; workspaces CRUD | Typed |
| `/creation/*` | `creation.py` | start-project, creation-state, brief, brief/{rev}/confirm, plans, plans/{id}/confirm (LEGACY recovery gate), brief/generate, plans/generate | Typed (LEGACY/COMPAT surface) |
| `/projects` | `projects.py` | POST /projects, GET workspaces/{wid}/projects, GET /projects/{id}, PUT preferences/experience-mode; **mounts workbench.router** | Typed |
| *(workbench, nested)* | `workbench.py` | workspace-state GET/PATCH, shots/{sid}/design, shots/{sid}/workbench, shots/{sid}/execution-plan, executions, formal-keyframe, formal-video, runs/{rid}/trace, repair-plan, repair | **`GET shots/{sid}/workbench` → `dict[str, object]` (§9.1 gap)** |
| `/projects/{pid}/director/*` | `director.py` | 20+ POST commands (workflow, budget-authorizations, artifact-versions, approvals, change-proposals, creative/*, shooting/package/generate, trial/*, production/*, repairs/*) | Typed (COMPAT/LEGACY Director surface) |
| `/projects/{pid}/shots/{sid}/director-board` | `director_board.py` | GET/PUT director-board, PATCH P8 board | Typed (P8) |
| `/projects/{pid}` production | `production.py` | snapshot, dispatch, node-runs/{id}/enqueue, produce-golden, exports POST, exports/{id}/download-grant, artifacts/{id}/content, artifacts/{id}/video-frames/{role} | Typed |
| `/projects/{pid}/scenes*` | `scenes.py` | list, workspace, reorder, copy, split-preview, split, merge-preview, merge | **ALL → `dict[str, object]` / `list[dict[str, object]]` (§9.1 gap)** |
| `/projects/{pid}/scripts*` | `scripts.py` | scripts/import, shot change proposals, shots list | Typed |
| `/projects/{pid}/characters/lead` | `characters.py` | register lead character | Typed |
| `/projects/{pid}/assets*` | `assets.py` | assets CRUD, versions, tags, recycle/restore, from-artifact, card | Typed |
| `/projects/{pid}/asset-tags` | `assets.py` | tag vocabulary | Typed |
| `/projects/{pid}/shots/{sid}/annotations*` | `review.py` | review annotations CRUD + decision | Typed |
| `/projects/{pid}/model-candidates` | `model_candidates.py` | read-only candidate list | Typed |
| `/capabilities`, `/models`, `/projects/{pid}/generations*` | `generations.py` | unified Generation API (NodeRun-backed) | Typed |
| `/model-slots`, `/workspaces/{wid}/model-profiles*`, `/projects/{pid}/model-profile`, `/projects/{pid}/model-bindings/effective`, `/model-profiles/validate` | `model_profiles.py` | model profiles CRUD | Typed |
| `/provider-plugins`, `/workspaces/{wid}/provider-connections*`, `/projects/{pid}/provider-bindings/{purpose}` | `provider_connections.py` | connections, probes, model bindings, quality evidence, project binding | Typed |
| `/workspaces/{wid}/provider-credentials` | `credentials.py` | workspace credential set/get | Typed |
| `/provider-references/{token}` | `provider_references.py` | public token GET | Typed |
| `/projects/{pid}/references*` | `references.py` | ShotReferenceBinding CRUD + `@Asset` UUID resolution (`BindingRead` / `ResolvedReferenceRead`) | Typed (P2-05/06) |
| `/projects/{pid}/shots/{sid}/...` | `shot_ops.py` | shot status/actions/manual-upload | Typed |
| `/projects/{pid}/experiments*` | `experiments.py` | experiment CRUD/start/decision/adopt | Typed |
| `/projects/{pid}/opencut-manifest` | `opencut.py` | OpenCut trace/clips | Typed |
| `/projects/{pid}/workflow-state`, `/workflow-overview`, `/shots/{sid}/workflow-state`, `/freeze` | `workflow_planning.py`, `workflow_overview.py` | WF13 read models | Typed (wraps `dict[str, object]` inside a Pydantic model) |
| `/projects/{pid}/creative-capabilities/{catalog,freeze,provenance}` | `creative_capabilities.py` | capability catalog/freeze | Typed |
| `/events/stream` | `events.py` | SSE stream | — |
| `/worker/tick` | `worker.py` | worker-only HTTP tick (dev substitute) | — |
| `/status` | `router.py` | health probe | `dict[str, Any]` (health only) |

## 3. `dict[str, object]` canonical API findings (方案 §9.1 "禁止新增", §18.1 fail-closed)

Only these canonical API routes use `response_model=dict[str, object]` — **9 total** (8 routes in `scenes.py` + 1 in `workbench.py`). Verified with `grep`; the set of affected files is `scenes.py` + `workbench.py` and nothing else in `api/v1`.

| File | Route(s) | Status |
|---|---|---|
| `backend/app/api/v1/scenes.py` | `GET /projects/{pid}/scenes` (`list[dict[str, object]]`), `GET .../scenes/{sid}/workspace`, `POST .../reorder`, `/copy`, `/split-preview`, `/split`, `/merge-preview`, `/merge` (lines 32,45,60,82,101,120,146,165) | **Phase 2 target** — replace with `SceneSummaryRead[]`, `SceneWorkspaceRead` per §9.2 |
| `backend/app/api/v1/workbench.py` | `GET /projects/{pid}/shots/{sid}/workbench` (line 126) | **Phase 2 target** — replace with `ShotDesignRead` |

Excluded from the Canonical contract gap: `workflow_overview.py` / `workflow_planning.py` wrap a `dict[str, object]` **inside a Pydantic response** (this is a typed envelope, not a bare dict); `main.py` health uses `dict[str, Any]` (not business). All other `dict[str, object]` occurrences are JSON **column** typing or internal service return typing, not API response models.

## 4. Contract-status summary vs. Phase 2 gate

| §9.2 / §18 requirement | Current | Gate (Phase 2) |
|---|---|---|
| `SceneSummaryRead` / `SceneWorkspaceRead` / `ShotDesignRead` typed | Not yet (scenes + workbench still dict) | Replace dict responses |
| Explicit Request/Response Schema on all Canonical APIs | Mostly — two gaps above | No new `dict[str, object]` |
| OpenAPI as single contract source | Not yet wired | `generated.ts` from OpenAPI |
| `frontend/src/shared/api/generated.ts` | **Does not exist** | Create via `npm run api:generate` |
| `npm run api:generate` / `npm run api:check` | **Do not exist in `frontend/package.json`** | Add scripts |
| Frontend business API split from `lib/api.ts` | Not split (monolith ~70 calls) | `features/*/api.ts` |
| `frontend/src/types/api.ts` + `types/openapi.json` | Present but **not imported** by any `src` file | Wire to generated client |

> **Freeze note.** The frontend currently builds its DTOs by hand inside `lib/api.ts`; a `types/api.ts` generated artifact exists (via `openapi-typescript`) but is orphaned. This is the Phase 2 divergence to close, not a current contract.

## 5. Provider API sub-contract (方案 §5)

The provider-facing API is plugin-driven (ADR 0005) and reads its surface from the installed plugins: `GET /api/v1/provider-plugins` (catalog + active model directory) drives provider configuration; connections/probes/bindings are per-plugin. Provider configuration never hard-codes provider name / Base URL / protocol / model ID / capability list in the frontend. Model selection is fail-closed via `ExecutionModelResolver` + `ModelSelectionService` (no silent X→Y).
