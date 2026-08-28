# CODE_OWNERSHIP_MATRIX

**Branch:** `dev` · **Freeze HEAD:** `237741f37f84cfbe71b37177772ca50e2d20646c` · **Alembic head:** `20260827_0049` · **Date:** 2026-08-28

> **Method.** This matrix freezes **actual logical domain ownership** of every top-level module in `backend/app` and `frontend/src`, plus the方案 §10 / §7.2 **target-domain** mapping. The repo does **not** use the方案 §10 target layout (`project/ story/ asset/ execution/ …`); it uses a domain-divided but differently-named layout. Per §29.9, we record the real layout as the source of truth and mark the方案 §10 layout as the **consolidation target**, not a current fact.

Classification legend: `CANONICAL` = formal chain; `COMPAT` = additive/compat, no new features; `LEGACY` = read-only or awaiting removal; `PLACEHOLDER` = empty/not-realized; `EXPERIMENTAL` = future capability, not part of first real film.

---

## 1. Backend — `backend/app`

| Package | Files | Logical domain | Writes tables | Classification | §10 target domain |
|---|---|---|---|---|---|
| `api` / `api/v1` | 3 / 29 | HTTP session + all routers | no (delegates) | CANONICAL | (router layer) |
| `access` | 6 | User / Workspace / Project | users, workspaces, projects, user_project_preferences, instance_bootstrap_state | CANONICAL | **project** |
| `assets` | 9 | Script/Episode/Scene/Shot + Asset/Character | script_documents, episodes, scenes, shots, canvas_revisions, shot_change_proposals, assets, asset_versions, asset_version_references, characters, character_references, asset_tags, asset_tag_links | CANONICAL | **story** + **asset** |
| `creation` | 3 | Brief/Plan/Authorization + AgentRun (legacy-recovery) | creative_briefs, creative_brief_revisions, creation_plans, planning_authorizations, agent_runs | LEGACY/COMPAT (recovery-only gate) | **agent** (partial) |
| `director` | 26 | Controlled Director workflow + Director Assist + creative capability (Part B) | director_workflow_runs, creative_artifact_versions, budget_authorizations, approval_records, change_proposals, impact_reports, workflow_step_runs, director_issues, production_batches, production_batch_shots, budget_reservations, director_threads, director_messages, director_proposals, director_proposal_items | CANONICAL (mixed: contains legacy 0018 block) | **agent** |
| `director/workflows` | 16 | Workflow Template framework (WF2), pure facts | none (writes Shot.director_state JSON via services) | CANONICAL | **agent** |
| `director/creative_capabilities` | 14 | Creative Capability Library, pure typed facts | none | CANONICAL (EXPERIMENTAL Part B) | **agent** |
| `production` | 11 | ProductionGraph/versions + formal selection + repair + experiment | production_graphs, experiment_branches, director_board_states, graph_versions, shot_reference_bindings, production_experiments, shot_experiments | CANONICAL | **production** |
| `execution` | 13 | Graph nodes/runs/artifacts/provider ops | graph_nodes, graph_edges, artifacts, node_runs, shot_human_locks, provider_operations | CANONICAL (one LEGACY helper: `pipeline.py`) | **execution** |
| `providers` | 47 (+9 model_profiles, +5 contracts, +5 litellm_gateway) | Provider adapters/catalog/registry/connections/bindings | provider_connections, provider_connection_revisions, provider_capability_evidence, provider_model_bindings, project_provider_bindings, provider_quality_evidence, artifact_reference_tokens, provider_model_catalog_entries, production_model_profiles | CANONICAL core (COMPAT V3 sub-layers) | **providers** |
| `providers/contracts` | 5 | Typed provider request/result contracts | none | CANONICAL | **providers** |
| `providers/litellm_gateway` | 5 | LiteLLM HTTP gateway client/catalog | none | EXPERIMENTAL (flag `text_v3_router_enabled` off) | **providers** |
| `providers/model_profiles` | 9 | ProductionModelProfile domain | production_model_profiles | CANONICAL | **providers** |
| `workbench` | 4 | Professional workbench app services (P1) | none (service layer over assets) | CANONICAL | **production** |
| `consistency` | 5 | continuity/identity/drift checks | none (pure dataclasses + cv2) | PLACEHOLDER/EXPERIMENTAL (consumed, no router) | **execution** |
| `delivery` | 5 | export + review annotations | review_annotations, exports, export_items | PARTIAL/CANONICAL-ish | **delivery** + **review** |
| `editing` | 4 | edit sessions (Phase 9) | edit_sessions | PLACEHOLDER/EXPERIMENTAL (no router wired) | **delivery** |
| `events` | 5 | event log + transactional outbox + SSE | event_log, outbox_events, outbox_dead_letters | CANONICAL | **shared** |
| `runtime` | 2 | schedulers (outbox/Arq) | no (enqueues) | CANONICAL | **execution** |
| `security` | 4 | BYOK credential encryption + rotation | encrypted_provider_credentials, key_rotation_audits | CANONICAL | **providers** |
| `shared` | 11 | cross-cutting primitives | no | CANONICAL | **shared** |
| `storage` | 2 | MinIO object store adapter | no | CANONICAL | **shared** |
| `workers` | 6 | Arq worker entrypoints (default/heavy) | no (executes NodeRuns) | CANONICAL | **execution** |

---

## 2. Frontend — `frontend/src`

| Module | Files | What it is | Classification |
|---|---|---|---|
| `routes/` | 11 | Real TanStack route tree (the app's surface) | CANONICAL |
| `lib/api.ts` | 1 (1459 l) | REST client + all business API calls | CANONICAL (§9.4 split is a Phase 2 target) |
| `lib/modelProfile.ts`, `lib/manifestOptions.ts`, `lib/zh.ts` | 3 | Live helpers | CANONICAL |
| `features/creation-preview/` | 8 | `ProjectWorkspaceShell` + `ProjectLobbyShell` (real nav) + mock quick-creation UI | CANONICAL (shells) — contains mock parts (`QuickCreationPreview`, `mockData`) |
| `features/workbench/` | 7 | Scene wall / scene workspace / shot workbench (real API) | CANONICAL |
| `features/assets/` | 2 (+.gitkeep) | Asset cards panel + feature-local API | CANONICAL |
| `features/production/` | 4 (+.gitkeep) | Production monitor + professional workbench | CANONICAL |
| `components/workstation/WorkstationShell.tsx` | 1 | Root layout | CANONICAL |
| `components/shell/`, `components/ui/`, `components/provider/`, `components/assets/` | 2,1,2,2 | AppShell/TopBar/Sidebar, primitives, provider panel/model-profile, AssetReferencePicker | CANONICAL (`components/assets/AssetMentionInput.tsx` orphaned) |
| `hooks/useProjectWorkspaceState.ts`, `stores/uiStore.ts` | 2 | last-view persistence, left-nav state | CANONICAL |
| `features/director/` | 12 | Legacy Director workflow stage UIs + api/types | COMPAT (only `api.ts`/`stageMap.ts`/`types.ts` imported; stage UIs orphaned) |
| `components/shared/ManifestOptionControls.tsx` | 1 (+.gitkeep) | capability-spec form control (no route consumer) | COMPAT/LEGACY |
| `lib/quickWorkflow.ts` | 1 | Quick-mode state normalization (tests only) | LEGACY |
| `lib/artifactStage.tsx`, `lib/useStageArtifact.ts`, `lib/projectMedia.ts`, `lib/queryKeys.ts` | 4 | Orphaned helpers (no `src` importer) | LEGACY |
| `features/experiments/ExperimentCompare.tsx` | 1 | A/B compare presentational (no importer) | EXPERIMENTAL |
| `features/model-controls/` | 5 | model-picker/form components (no route import) | EXPERIMENTAL |
| `features/review/` | 3 (+.gitkeep) | review canvas/timeline (no importer) | EXPERIMENTAL |
| `features/audit/`, `features/creation/`, `features/delivery/`, `features/projects/`, `features/storyboard/`, `components/sse/` | 1 each | empty `.gitkeep` only | PLACEHOLDER |
| `types/api.ts` + `types/openapi.json` | 2 | `openapi-typescript` generated output (not imported) | PLACEHOLDER (unwired generated artifact) |

---

## 3. Ownership rules (the load-bearing invariants)

1. **`Shot` / `Scene` / `Asset` / `Experiment` are creative facts — Agent produces typed proposals only**, and can never directly mutate them or call a Provider.
2. **`ProductionGraph` / `NodeRun` / `ProviderOperation` / `Artifact` are execution facts — no parallel Generation / AIJob / Runtime / cost-truth may be created.**
3. **The single execution authority is the Worker** (`backend/app/workers/jobs.py → backend/app/execution/product_path.py`). No API route may call a Provider for the shot media chain. **Known documented exception:** `api/v1/characters.py` `characters/lead` makes a synchronous in-request image Provider call to provision a lead character's canonical reference image — it still writes the same execution facts (`NodeRun` audit parent + `ProviderOperation` + `Artifact`) and is gated by `require_legacy_execution_allowed`; it is NOT a parallel truth, but is outside the strict "Worker-only" rule. Recorded in `PHASE_GATE.md` §4b (Recorded facts).
4. **`ModelManifest` is model-capability truth; `ProductionModelProfile` is preference; real-media execution consumes the frozen `ExecutionModelResolution`** — never a fresh binding read at resume.
5. **Provider plugin facts (Catalog + Binding probe + unique Compiler/Runtime + submission state machine) are canonical and single-sourced** (ADR 0005). `Connection`/`Credential`/`Catalog`/`Binding`/`Manifest`/`mode`/`reference` execution identity must be traceable, restorable, and not rewritten by later config.
6. **`creation-preview` is a Phase 1 migration target** — its two real shells (`ProjectWorkspaceShell`, `ProjectLobbyShell`) move to `components/workstation/` / `app/layouts/`; after that, formal business code must not import `creation-preview`.

---

## 4. Consolidation targets (not current facts)

| §10 target dir | Current home | Owner domain |
|---|---|---|
| `project/` | `access` | User/Workspace/Project |
| `story/` | `assets` (ScriptDocument/Episode/Scene/Shot/CanvasRevision/ShotChangeProposal) | Story |
| `asset/` | `assets` (Asset/AssetVersion/AssetVersionReference/Character/Tag) + `production` (ShotReferenceBinding) | Asset/Reference |
| `production/` | `production` + `workbench` (services) | Production |
| `execution/` | `execution` + `runtime` + `workers` | Execution |
| `review/` | `delivery` (ReviewAnnotation) + API `review.py` | Review |
| `delivery/` | `delivery` + `editing` | Delivery |
| `providers/` | `providers` + `security` | Providers |
| `agent/` | `director` (no `agent` package exists) | Agent |
| `shared/` | `shared` + `events` + `storage` | Shared |
