# DATA_MODEL_INVENTORY

**Branch:** `dev` · **Freeze HEAD:** `237741f37f84cfbe71b37177772ca50e2d20646c` · **Alembic head:** `20260827_0049` · **Date:** 2026-08-28

> **Purpose.** Freeze the database truth. **SQL strategy (方案 §12.1): no DB rebuild.** PostgreSQL + Alembic + RLS retained; the current Production/Execution/Provider tables are the base and there is no reason to re-initialize. This inventory gives every table a §12.3 classification (CANONICAL / COMPAT / LEGACY / PLACEHOLDER / EXPERIMENTAL) with its creating migration and ORM home.

---

## 1. Schema at a glance

- **Alembic head:** `20260827_0049` (single leaf).
- **Total migrations:** **49** (one linear chain, revisions 0001–0049, no branches).
- **Base:** `20260720_0001_s1_1_access_session.py` has `down_revision = None` — the effective root (no separate `base`/`boot` revision).
- **Naming convention:** `YYYYMMDD_NNNN_short_snake_name.py`.
- **No `op.rename` / no table dropped in any `upgrade()` path.** The only backward-incompatible changes are irreversible column/enum retirements (0025, 0026, 0029) and credential immutability (0041/0042).
- **ORM models are colocated per-domain** — there is **no** `backend/app/models/` directory. `backend/app/shared/model_registry.py::load_all_models()` registers every ORM module for worker processes.
- **RLS** (row-level security) is pervasive via `backend/app/shared/db.py` (`set_rls_context`, `set_node_run_rls_context`, …).

---

## 2. Canonical entity presence (方案 §12.2)

The §12.2 canonical enumeration lists **19** entities. **All 19 are present** (0 missing).

| Canonical entity | Table | Model file | Present |
|---|---|---|---|
| users | `users` | `access/models.py` | ✓ |
| workspaces | `workspaces` | `access/models.py` | ✓ |
| projects | `projects` | `access/models.py` | ✓ |
| script_documents | `script_documents` | `assets/models.py` | ✓ |
| episodes | `episodes` | `assets/models.py` | ✓ |
| scenes | `scenes` | `assets/models.py` | ✓ |
| shots | `shots` | `assets/models.py` | ✓ |
| assets | `assets` | `assets/models.py` | ✓ |
| asset_versions | `asset_versions` | `assets/models.py` | ✓ |
| asset_version_references | `asset_version_references` | `assets/models.py` | ✓ |
| shot_reference_bindings | `shot_reference_bindings` | `production/models.py` | ✓ |
| production_graphs | `production_graphs` | `production/models.py` | ✓ |
| graph_versions | `graph_versions` | `production/models.py` | ✓ |
| graph_nodes | `graph_nodes` | `execution/models.py` | ✓ |
| graph_edges | `graph_edges` | `execution/models.py` | ✓ |
| node_runs | `node_runs` | `execution/models.py` | ✓ |
| provider_operations | `provider_operations` | `execution/models.py` | ✓ |
| artifacts | `artifacts` | `execution/models.py` | ✓ |
| outbox_events | `outbox_events` | `events/models.py` | ✓ |

> **Freeze note.** §12.2 also names these as canonical (CANONICAL per §16.3): `users/workspaces/projects/script_documents/episodes/scenes/shots/assets/asset_versions/asset_version_references/shot_reference_bindings/production_graphs/graph_versions/graph_nodes/graph_edges/node_runs/provider_operations/artifacts` + `provider_connections` and `provider_model_bindings` (§16.3 "首批目标分类 · CANONICAL"). Those two provider tables are present and canonical (see §4).

---

## 3. Full table inventory → classification

| Table | Domain | Model file | Creating migration | Classification |
|---|---|---|---|---|
| `users` | shared | `access/models.py` | `20260720_0001_s1_1_access_session.py` | CANONICAL |
| `workspaces` | shared | `access/models.py` | `20260720_0001_s1_1_access_session.py` | CANONICAL |
| `projects` | shared | `access/models.py` | `20260720_0002_s1_2_projects.py` | CANONICAL |
| `user_project_preferences` | shared | `access/models.py` | `20260720_0002_s1_2_projects.py` | COMPAT |
| `instance_bootstrap_state` | shared | `access/models.py` | `20260813_0019_instance_bootstrap_state.py` | COMPAT |
| `script_documents` | story | `assets/models.py` | `20260721_0007_script_assets.py` | CANONICAL |
| `episodes` | story | `assets/models.py` | `20260721_0007_script_assets.py` | CANONICAL |
| `scenes` | story | `assets/models.py` | `20260721_0007_script_assets.py` | CANONICAL |
| `shots` | story | `assets/models.py` | `20260721_0007_script_assets.py` | CANONICAL |
| `canvas_revisions` | story | `assets/models.py` | `20260825_0032_canvas_revisions.py` | CANONICAL (feature) |
| `shot_change_proposals` | story | `assets/models.py` | `20260825_0033_shot_change_proposals.py` | CANONICAL (feature) |
| `assets` | asset | `assets/models.py` | `20260721_0007_script_assets.py` | CANONICAL |
| `asset_versions` | asset | `assets/models.py` | `20260825_0035_asset_versions.py` | CANONICAL |
| `asset_version_references` | asset | `assets/models.py` | `20260826_0044_phase2_asset_references.py` | CANONICAL |
| `characters` | asset | `assets/models.py` | `20260721_0007_script_assets.py` | **COMPAT** (still written by `characters/lead`; backfilled to asset_versions by 0044, but the canonical-image route actively inserts new rows) |
| `character_references` | asset | `assets/models.py` | `20260721_0007_script_assets.py` | **COMPAT** (migration window; still written, backfilled by 0044) |
| `asset_tags` | asset | `assets/models.py` | `20260826_0044_phase2_asset_references.py` | CANONICAL (feature) |
| `asset_tag_links` | asset | `assets/models.py` | `20260826_0044_phase2_asset_references.py` | CANONICAL (feature) |
| `production_graphs` | production | `production/models.py` | `20260720_0003_s1_events_outbox_graphs.py` | CANONICAL |
| `graph_versions` | production | `production/models.py` | `20260720_0003_s1_events_outbox_graphs.py` | CANONICAL |
| `shot_reference_bindings` | production | `production/models.py` | `20260826_0044_phase2_asset_references.py` | CANONICAL |
| `experiment_branches` | production | `production/models.py` | `20260825_0036_experiment_branches.py` | CANONICAL (feature) |
| `director_board_states` | production | `production/models.py` | `20260825_0038_director_board_states.py` | CANONICAL (feature) |
| `production_experiments` | production | `production/models.py` | `20260827_0045_production_experiments.py` | CANONICAL (feature) |
| `shot_experiments` | production | `production/models.py` | `20260827_0045_production_experiments.py` | CANONICAL (feature) |
| `graph_nodes` | execution | `execution/models.py` | `20260721_0004_execution_creation_tables.py` | CANONICAL |
| `graph_edges` | execution | `execution/models.py` | `20260721_0004_execution_creation_tables.py` | CANONICAL |
| `artifacts` | execution | `execution/models.py` | `20260721_0004_execution_creation_tables.py` | CANONICAL |
| `node_runs` | execution | `execution/models.py` | `20260721_0004_execution_creation_tables.py` | CANONICAL |
| `provider_operations` | execution/provider | `execution/models.py` | `20260721_0004_execution_creation_tables.py` | CANONICAL |
| `shot_human_locks` | execution | `execution/models.py` | `20260721_0006_exports_locks.py` | CANONICAL (feature) |
| `materialization_operations` | execution | **no ORM model (orphaned)** | `20260721_0004_execution_creation_tables.py` | **LEGACY/PLACEHOLDER** (created + RLS'd, no model) |
| `event_log` | shared | `events/models.py` | `20260720_0003_s1_events_outbox_graphs.py` | CANONICAL (feature) |
| `outbox_events` | shared | `events/models.py` | `20260720_0003_s1_events_outbox_graphs.py` | CANONICAL |
| `outbox_dead_letters` | shared | `events/models.py` | `20260720_0003_s1_events_outbox_graphs.py` | CANONICAL (feature) |
| `creative_briefs` | creation | `creation/models.py` | `20260721_0004_execution_creation_tables.py` | LEGACY/COMPAT |
| `creative_brief_revisions` | creation | `creation/models.py` | `20260721_0004_execution_creation_tables.py` | LEGACY/COMPAT |
| `creation_plans` | creation | `creation/models.py` | `20260721_0004_execution_creation_tables.py` | LEGACY/COMPAT |
| `planning_authorizations` | creation | `creation/models.py` | `20260721_0004_execution_creation_tables.py` | LEGACY/COMPAT |
| `agent_runs` | creation | `creation/models.py` | `20260721_0004_execution_creation_tables.py` | CANONICAL (director-assist uses `operation='director_assist'`) |
| `provider_connections` | provider | `providers/models.py` | `20260803_0014_provider_connections_reference_delivery.py` | CANONICAL |
| `provider_connection_revisions` | provider | `providers/models.py` | `20260826_0042_provider_connection_revisions.py` | CANONICAL |
| `provider_capability_evidence` | provider | `providers/models.py` | `20260803_0014_provider_connections_reference_delivery.py` | CANONICAL |
| `provider_model_bindings` | provider | `providers/models.py` | `20260803_0014_provider_connections_reference_delivery.py` | CANONICAL |
| `project_provider_bindings` | provider | `providers/models.py` | `20260803_0014_provider_connections_reference_delivery.py` | CANONICAL (COMPAT fallback, `explicit_binding` only) |
| `provider_quality_evidence` | provider | `providers/models.py` | `20260803_0014_provider_connections_reference_delivery.py` | CANONICAL |
| `artifact_reference_tokens` | provider | `providers/models.py` | `20260803_0014_provider_connections_reference_delivery.py` | CANONICAL |
| `provider_model_catalog_entries` | provider | `providers/catalog_models.py` | `20260810_0015_provider_catalog_and_unified_path.py` | CANONICAL (global read-only, seeded from `_seeds_0015.py`) |
| `production_model_profiles` | provider | `providers/model_profiles/orm.py` | `20260811_0017_production_model_profiles.py` | CANONICAL |
| `encrypted_provider_credentials` | security | `security/models.py` | `20260724_0008_byok_keyring.py` | CANONICAL (immutable revision model added by 0041) |
| `key_rotation_audits` | security | `security/models.py` | `20260724_0008_byok_keyring.py` | CANONICAL (feature) |
| `exports` | delivery | `delivery/models.py` | `20260721_0006_exports_locks.py` | CANONICAL (feature) |
| `export_items` | delivery | `delivery/models.py` | `20260721_0006_exports_locks.py` | CANONICAL (feature) |
| `review_annotations` | review | `delivery/models.py` | `20260825_0037_review_annotations.py` | CANONICAL (feature) |
| `director_workflow_runs` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent (controlled-Director block) |
| `creative_artifact_versions` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `budget_authorizations` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `approval_records` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `change_proposals` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `impact_reports` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `workflow_step_runs` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `director_issues` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `production_batches` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `production_batch_shots` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `budget_reservations` | director | `director/models.py` | `20260813_0018_director_workflow_core.py` | LEGACY-adjacent |
| `director_threads` | director | `director/models.py` | `20260827_0047_director_threads.py` | CANONICAL (Phase 7) |
| `director_messages` | director | `director/models.py` | `20260827_0047_director_threads.py` | CANONICAL (Phase 7) |
| `director_proposals` | director | `director/proposal_models.py` | `20260827_0048_director_proposals.py` | CANONICAL (Phase 7) |
| `director_proposal_items` | director | `director/proposal_models.py` | `20260827_0048_director_proposals.py` | CANONICAL (Phase 7) |
| `edit_sessions` | editing | `editing/models.py` | `20260827_0049_edit_sessions.py` | EXPERIMENTAL (Phase 9) |

---

## 4. Legacy / obsolete candidates (frozen, for §12.3 and Phase 8)

### 4.1 Characters migration window
`characters` + `character_references` were backfilled into `asset_versions` / `asset_version_references` by `20260826_0044_phase2_asset_references.py` (each `Character` → immutable `AssetVersion` v1; `CharacterReference` → `AssetVersionReference`). They remain **readable during the migration window**, and are **still actively written** by the `characters/lead` canonical-image route (`register_lead_character`, `backend/app/assets/characters.py`). Classified **COMPAT** (not LEGACY) because they receive new writes on the live path. **No drop migration exists.** The Phase 8 removal gate therefore cannot pass for these two tables until `characters/lead` stops writing them (or they are migrated to `asset_versions`/`asset_version_references` for lead registration).

### 4.2 `materialization_operations` (orphaned)
Created `20260721_0004`, RLS-policy applied in 0005, but **no ORM model exists anywhere** in `backend/app` (grep for the name returns zero matches). It is an orphaned table. **No removal migration.**

### 4.3 Controlled-Director workflow block (`20260813_0018`)
`director_workflow_runs`, `creative_artifact_versions`, `budget_authorizations`, `approval_records`, `change_proposals`, `impact_reports`, `workflow_step_runs`, `director_issues`, `production_batches`, `production_batch_shots`, `budget_reservations`. These are the **older controlled-Director workflow + production_batch** system. They still have ORM models (`director/models.py`) so not fully dead, but the **Phase 7 Director Assist** path (0046 `agent_runs.operation='director_assist'`, 0047 `director_threads`/`director_messages`, 0048 `director_proposals`/`director_proposal_items`) is the canonical successor and relaxes `planning_authorization_id` to NULL. **Classify the 0018 block LEGACY-adjacent; no removal migration exists (only reversible downgrades).**

### 4.4 Absences (confirmed)
No quick-workflow tables; no gallery/posts tables; no DB-backed job/task table. **Quick mode is a column** (`experience_mode='quick'` on `projects` / `user_project_preferences`), not a table. Worker jobs are Arq/Redis-backed (`backend/app/workers/jobs.py`) — Postgres holds no job table.

---

## 5. Migration-phase notes

- **Foundation (0001–0008):** users/workspaces (`0001`), projects/preferences (`0002`), event_log/outbox/production_graphs/graph_versions (`0003`), execution+creation (`0004`), RLS (`0005`), exports/locks (`0006`), script/asset/character (`0007`), BYOK keyring (`0008`).
- **RLS/dispatch hardening (0009–0013).** **Provider layer (0014–0017):** connections/evidence/bindings, catalog+unified path, binding revision uniqueness, production model profiles. **Director core + runtime hardening (0018–0031):** director workflow block, bootstrap state, pricing snapshot, catalog seeds, role/auth, face-review retirement, resumable provider runs. **Professional workspace / Phase 2+ (0032–0049):** canvas revisions, shot change proposals, asset_versions, experiment branches, review annotations, director board states, spatial annotations, immutable credentials, connection revisions, professional workspace foundation, phase-2 asset references, production experiments, director assistant, edit sessions.
