# CANONICAL_PRODUCT_PATH

**Branches:** `dev`  
**Doc type:** Phase 0 Architecture Freeze — canonical product path (the 唯一正式作品链)  
**Freeze at HEAD:** `237741f37f84cfbe71b37177772ca50e2d20646c`  
**Alembic head:** `20260827_0049`  
**Audit date:** 2026-08-28  
**Authority:** `DramaForge_dev_架构收敛设计与执行方案.md` (§3 / §4 / §5 / §6), read against actual `dev` code.

> **Divergence from the方案 intro (recorded, per §29.9 "以真实代码事实为准记录差异"):** the方案 §1 describes `dev` as "多代架构共存" with a low product-surface completeness. The frozen reality is that the seven-plan program (`docs/plans/professional-program-v2/`) Phase 1–10 has **already landed** on `dev` at this HEAD: the canonical runtime path executes through the Worker, the execution-identity freeze (MS1–MS5) is merged and green, Quick is already a Legacy retire notice, and a real paid-provider golden run has passed. This document therefore freezes **actual ground truth**, not the方案's stale assumptions. Where a方案 target does not yet exist (e.g. `frontend/src/shared/api/generated.ts`, frontend business-API split, `/review` + `/settings` routes), it is listed as **not-yet-present** rather than assumed.

---

## 1. The one product chain (方案 §3)

There is exactly one formal production chain. Every feature must attach to a layer of it.

```text
Project
  ↓
ScriptDocument
  ↓
Episode
  ↓
Scene
  ↓
Shot
  ↓
Asset / Reference
  ↓
Shot Design
  ↓
Keyframe
  ↓
Video
  ↓
Review / Repair
  ↓
Edit / Timeline
  ↓
Delivery
```

**Freeze facts:**

- **Shot is the核心 production unit.** Its canonical fields are `director_state`, `image_prompt`, `video_prompt`, `formal_keyframe_artifact_id`, `formal_video_artifact_id`, `formal_composite_artifact_id`, plus `visual_description`, `dialogue`, `duration_seconds`, `shot_type`, `camera_move` (§8.3). No parallel `ProfessionalShot` / `DirectorShot` / `WorkflowShot` entity exists and none may be created.
- **Story domain lives in `backend/app/assets`** (`ScriptDocument`/`Episode`/`Scene`/`Shot`/`CanvasRevision`/`ShotChangeProposal` are all in `backend/app/assets/models.py`). There is **no** `backend/app/story` package and **no** `backend/app/workbench` package acting as its own entity; `app/workbench` is a service layer over `app/assets`, not a parallel entity family.
- **Frontend route tree (actual, at freeze):**
  ```
  __root  → routes/__root.tsx (RootLayout → WorkstationShell)
  ├── /                                       HomePage (ProjectLobbyShell; auth/workspace/project CRUD)
  ├── /projects/$projectId                    ProjectLayout (ProjectWorkspaceShell)
  │   ├── /quick                              QuickLegacyNotice  — LEGACY retire page ("Quick 模式已退役")
  │   ├── /script                             ScriptPage          — present (Phase 1 placeholder surface)
  │   ├── /assets                             AssetsPage → AssetCardsPanel
  │   ├── /scenes                             ScenesPage → SceneStoryboardWall
  │   ├── /scenes/$sceneId                    SceneWorkspacePage → SceneWorkspace
  │   ├── /production                         ProductionPage (WorkflowNavigator + CreativeCapabilitiesPanel + ProductionMonitor + ProfessionalWorkbench + export)
  │   └── /edit                               EditPage            — present (Phase 1 placeholder surface)
  ├── /design-preview                         DesignPreviewPage (design-system showcase)
  └── /design-preview/product                 QuickCreationPreview (mock product preview)
  ```
  - **Not yet present (divergence vs §7.1):** `/projects/:projectId/review` and `/projects/:projectId/settings` routes do **not** exist. The sidebar exposes script/assets/scenes/production/edit only; "模型设置" is an anchor link (`/projects/$projectId#model-settings`) on the project overview, not a route.
  - **The default post-login / post-project-create target is `/projects/$projectId/production`** (`routes/index.tsx`).
  - `WorkstationShell` (canonical, in `components/workstation/`) renders children raw for real routes; the legacy shell wraps only non-product paths.

---

## 2. Asset / Reference chain (方案 §4.2)

```text
Asset
  ↓
AssetVersion
  ↓
AssetVersionReference
  ↓
ShotReferenceBinding
  ↓
Shot
```

**Freeze facts:**

- `AssetVersion` is **immutable** — no in-place overwrite. `Asset.current_version_id` is the `current_formal` pointer.
- `ShotReferenceBinding` (`backend/app/production/models.py`) is the **single** reference system. It carries `shot_id`, `purpose`, `resolution_mode`, `asset_id`, `asset_version_id`, `artifact_id`, `stage`.
  - `purpose` values: `identity`, `clothing`, `scene_layout`, `scene_lighting`, `style`, `action`, `pose`, `camera_language`, `audio_rhythm`, `first_frame`, `last_frame`, `generic_reference`.
  - `resolution_mode` values: `current_formal` / `pinned_version` / `direct_artifact`.
- **Reference resolution must not guess** via asset name, prompt `@角色`, or current UI state. Execution resolves through `shot_reference_bindings` into a concrete `asset_version_id` or `artifact_id`.
- **Legacy migration window (frozen, not yet removable):** the older `characters` / `character_references` tables were backfilled into `asset_versions` / `asset_version_references` by migration `20260826_0044_phase2_asset_references.py`. They remain readable during the migration window; **no drop migration exists yet** (Phase 8 removal precedes any drop).

---

## 3. Production execution chain (方案 §4.3)

The one formal execution chain — media execution **must** run here, never via `Frontend → API → Provider → URL`.

```text
Shot
  ↓
ProductionGraph
  ↓
GraphVersion
  ↓
GraphNode
  ↓
NodeRun
  ↓
ProviderOperation
  ↓
Artifact
```

**Freeze facts (code evidence):**

| Step | Location |
|---|---|
| Shot | `backend/app/assets/models.py` (`class Shot`) |
| ProductionGraph / GraphVersion | `backend/app/production/models.py` (`production_graphs`, `graph_versions`, immutable `definition_hash` after PUBLISHED) |
| GraphNode / GraphEdge | `backend/app/execution/models.py` (`graph_nodes`, `graph_edges`) |
| NodeRun / Artifact / ProviderOperation | `backend/app/execution/models.py` |
| Graph materialize/publish | `backend/app/production/service.py` (`GraphService`) |
| Reference compile | `backend/app/production/reference_intents.py` |
| Plan (frozen, with fingerprint) | `backend/app/production/execution_plan.py` (`WorkbenchExecutionPlan`) |
| Plan execution service | `backend/app/production/workbench_execution.py` (`WorkbenchExecutionService`) |
| **Worker that calls the Provider** | `backend/app/workers/jobs.py` → `backend/app/execution/product_path.py` (`execute_media_node_run` → `_execute_unified_media_node_run`) |

**Media provider calls happen in a Worker for the canonical shot-production path (keyframe → video → composite).** API routes create `status="queued"` NodeRuns and enqueue via Outbox + Arq (`backend/app/runtime/scheduler.py`, `AgentRunScheduler`); the Provider is called in `backend/app/workers/jobs.py` → `backend/app/execution/product_path.py`. The dev-only `/worker/tick` route runs adapters in-process but is token-gated (not the product path).

**One documented execution-composition nuance (`characters/lead`).** `POST /projects/{id}/characters/lead` (`backend/app/api/v1/characters.py`) provisions a lead character's canonical reference image. It **does** satisfy the canonical chain: `create_canonical_generation_run` (`backend/app/assets/characters.py:42-106`) builds a real one-node `ProductionGraph` + `GraphVersion` via `GraphService.create_graph`, adds a `GraphNode`, and creates the `NodeRun` referencing `graph_version_id`/`graph_node_id`; `record_canonical_provider_operation` writes the `ProviderOperation`, and the artifact is stored with a `canonical_artifact_id` + `canonical_content_hash`. It is **not** the §4.3 prohibited `Frontend → API → Provider → URL` bypass (it returns a `content_hash`, not a raw provider URL, and writes the canonical execution facts). The one deviation is that the Provider call is **synchronous in the request thread** rather than Worker-deferred — accepted in the shipped V1 program (the golden run used it) and gated by `require_legacy_execution_allowed`. Recorded in `PHASE_GATE.md` §4b (Recorded facts); a later-phase task could move it to Worker-deferred without changing facts.

**Formal selection is human-confirmed, never auto-formal:** `backend/app/production/formal_selection.py` (`set_formal_keyframe` / `set_formal_video` / `require_formal_keyframe`) fails closed with no "latest image" fallback. Candidates are never promoted to Formal without explicit user confirmation.

---

## 4. Provider architecture chain (方案 §5)

Provider is a **capability + account + cost + recovery** layer, not a product-structure center. The formal execution chain:

```text
User Selection
  ↓
ProductionModelProfile        (preference)
  ↓
ProviderModelBinding
  ↓
Provider Connection Revision   (immutable execution config)
  ↓
Capability Manifest           (ModelManifest / ModelCapabilityManifest)
  ↓
Compiler / Runtime            (per-plugin)
  ↓
Execution Plan                (WorkbenchExecutionPlan, frozen + fingerprint)
  ↓
NodeRun
  ↓
ProviderOperation
```

**Freeze facts:**

- **"用户选 X，实际执行就是 X" is enforced fail-closed.** `ExecutionModelResolver` (`backend/app/providers/model_resolution.py`) resolves request override → project profile slot → workspace profile slot → system default at **slot level**; once a higher-priority source names X, an unavailable X is **terminal** and never falls through to a legacy binding Y. `ModelSelectionService` raises `MODEL_INELIGIBLE` on remaining issues. The unified path enforces `MODEL_BINDING_SNAPSHOT_MISMATCH` / `EXECUTION_IDENTITY_MISMATCH` before every submission.
- **Execution uses the task-creation-frozen revision, not fresh config on resume.** `ProviderRuntimeResolver.resolve_runtime_for_identity` reconstructs a `FrozenProviderConnection` **from `ProviderConnectionRevision`**; the mutable `ProviderConnection` is joined only to authorize workspace/connection ownership. Resume never creates a second remote task (`unknown_submission` is terminal, no duplicate POST).
- `ProviderOperation` (`backend/app/execution/models.py`) freezes `connection_id`, `provider_connection_revision_id`, `model_binding_id`, `catalog_entry_id`, `capability_manifest_hash`, `selection_plan`, `execution_path_version`, `actual_provider`, `actual_model`, plus `resume_token` / `request_fingerprint`.
- **Plugin architecture (ADR 0005) is canonical:** immutable global Catalog (`provider_model_catalog_entries`, seeded from a frozen snapshot `backend/alembic/_seeds_0015.py`) + binding-level Probe (`ProviderConnectionService.probe`, "proving one model must never advance a sibling binding") + unique per-plugin Compiler/Runtime (agnes / volcengine / minimax) + submission state machine (`created → submission_started → submitted → running → {succeeded, failed, timed_out, unknown_submission, rejected}`).
- **LiteLLM is text-only** and is a separate runtime reached over HTTP (`backend/app/providers/litellm_gateway/`). Media wires are agnes / volcengine / minimax.
- **Caveats frozen (explicit, not silent):** `ResolutionSource` declares `"fallback"` but the resolver never emits it (declared-only, not live). `ModelSelectionIntent` declares `auto` / `project_default` modes that are not yet open — placeholders, not live behavior. The V3 text router and the unified media path are gated by config flags whose **code default is `False`** (`text_v3_router_enabled=False`, `provider_unified_path_enabled=False`, `provider_unified_shadow=False` in `backend/app/config.py`), **but the local deployment `.env` sets `TEXT_V3_ROUTER_ENABLED=true` and `PROVIDER_UNIFIED_PATH_ENABLED=true`**, so the running deployment uses the unified/V3 path. Because `.env` is gitignored, the flag truth is deployment-specific — the code default (legacy adapter path reachable for non-Director projects) is the safe assumption when no `.env` override is present.

---

## 5. Director Agent path (方案 §6)

Director Agent is an **assist layer**, not an independent product flow. It proposes; the user accepts; the fact changes.

```text
Director Agent
  ↓
ShotChangeProposal / DirectorProposal / ChangeProposal
  ↓
UI → User Accept (or Reject)
  ↓
Shot
  ↓
CanvasRevision
```

**Freeze facts:**

- There is **no `backend/app/agent` package**. The agent subsystem is `backend/app/director/`.
- `DirectorAgentRuntime` (`backend/app/director/agent_runtime.py`) executes text skills **without mutating creative facts**; the caller must validate output and publish a proposal/version separately.
- All agent suggestions are reviewable, typed proposals: `ShotChangeProposal` (`app/assets/models.py`, applied only via `confirm_shot_change_proposal`), `DirectorProposal`/`DirectorProposalItem` (`app/director/proposal_models.py`, applied via `ProposalService.partial_apply` through the `ProposalCommandRegistry` whitelist — rejected items are never executed, shot-mutating commands require `expected_target_version` and fail `PROPOSAL_STALE` on drift), and `ChangeProposal` for locked workflow creative artifacts.
- **The Director does not write Shot rows directly.** Media execution is dispatched through the standard NodeRun/Worker path behind `validate_director_media_submission` (`app/director/execution_guard.py`).

---

## 6. Canonical status model (方案 §13)

- **Shot states — 方案 §13.1 target vs actual (recorded deviation).** The方案 §13.1 *recommends* unifying to `draft` / `ready` / `producing` / `review` / `approved` / `blocked`. **The code has NOT adopted this.** `Shot.status` is a free-form `String(20)` column (`backend/app/assets/models.py:109`, default `"draft"`) with no central enum; observed writes across `backend/app` are `draft`, `failed`, `in_production`, `awaiting_review`, `review_passed`, `review_rejected`, `accepted`, `repair_requested`, `stopped`, `review`, `blocked`. Normalizing to the §13.1 set is a **later-phase task**, not a current fact. (Consistent rule that IS current: UI must not present `ProviderOperation` status as a `Shot` status.)
- **NodeRun states:** execution-layer states (owned by `backend/app/execution`; free-form status string, notably `queued` / `running` / `failed` / `succeeded` / `submission_*`).
- **Artifact states:** `quarantined` / `available` / `cold` / `delete_requested` / `deleted` (lifecycle as documented).

---

## 7. Canonical infrastructure (方案 §15)

Frozen at: PostgreSQL, Redis, MinIO, LiteLLM, FastAPI, Outbox Dispatcher, ARQ Worker Default + Heavy, Frontend/Nginx. **No new infrastructure component is to be added before a real first production loop completes.** Infrastructure serves the Canonical Product Path only.

---

## 8. Frontend product architecture (方案 §7.2) — frozen targets vs present state

**Target feature tree (方案 §7.2):** `app/{router,layouts,providers}` + `features/{projects,script,assets,scenes,shots,production,review,edit,settings}` + `shared/{api,ui,hooks,types}`.

**Present state at freeze:**

- There is **no `frontend/src/app`** (app code lives at `frontend/src/routes` via TanStack Router) and **no `frontend/src/shared`** — only `frontend/src/components/shared`. The `app/` and `features/<many>/` target layout does **not** yet match; this is a **Phase 1+ refactor target, not a current fact**.
- `features/creation-preview/` contains the **real** app navigation: `ProjectWorkspaceShell` (the actual project layout, imported by `routes/projects.$projectId.tsx`) and `ProjectLobbyShell` (the real lobby). It also contains mock quick-creation UI (`QuickCreationPreview`, `mockData.ts`) used only by `/design-preview/product`. **Migrating the two shells into `components/workstation/`/`app/layouts/` is a Phase 1 target.**
- `features/workbench/` (real API): `SceneStoryboardWall`, `SceneWorkspace`, `ShotStrip`, `CinematicCanvas`, `ShotDesignPanel`, `ShotProductionTrace`, `api.ts`.
- **Business API vs http client split (方案 §9.4) is not yet done** — `frontend/src/lib/api.ts` (1459 lines) is the single monolith carrying base URL, workspace scoping, cookie session, CSRF, error normalization, artifact URLs **and** ~70 business calls. Splitting business calls into `features/*/api.ts` is a **Phase 2 target**; `features/assets/api.ts`, `features/workbench/api.ts`, `features/director/api.ts` already exist but still build on `lib/api`.

---

## 9. The one gate discipline (方案 §25)

Any PR into `dev` must state: which canonical chain (`Story` / `Asset` / `Production` / `Execution` / `Review` / `Delivery` / `Agent Assist`), the user-visible change, the Code/Contract/Evidence gates, and for production-chain changes the Project/Shot/NodeRun/ProviderOperation/Artifact IDs with no secret. A change that only "adds a table / abstraction / compiler / service" defaults to not-merging unless it unblocks the current phase.
