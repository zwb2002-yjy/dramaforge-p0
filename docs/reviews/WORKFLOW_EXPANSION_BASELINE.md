# Workflow Expansion Baseline / Drift Audit

**Document type:** Baseline Audit (WF0)
**Program:** Professional Program v2 — Workflow Expansion
**Scope:** Re-read the latest `dev` before implementing any Workflow Expansion task.

---

## Header

| Field | Value |
| --- | --- |
| BASE_HEAD | `18dfc51ddb2028602a3ebcf3c14c9b3a6dda4bbc` |
| BASE_HEAD_COMMIT | `docs: mark all professional program task contracts as complete` |
| DESIGN_BASELINE | `69aed7869b9dc978b4849d89e356c4eb97799da1` |
| MIGRATION_HEAD | `20260827_0049` (edit_sessions) |
| MIGRATION_BASE | `20260720_0001` |
| Backend unit tests | `831 passed` (pytest smoke on this baseline) |
| Branch | `dev` |

> The current `dev` is one commit past the design baseline (`69aed78`), a docs-only
> commit that marks professional-program task contracts complete. No code drift
> exists between the design baseline and the audit base.

---

## 2. Already Done (must not be re-implemented)

These are established facts of the current code and are reused as-is.

### Canonical Professional Path (frontend)

- `frontend/src/routes/projects.$projectId.quick.tsx` implements `QuickLegacyNotice` —
  `/projects/:projectId/quick` is a **Legacy Notice** and is **not** a default entry.
  - TestId `quick-legacy`.
  - Links to `/scenes` (场景工作区) and `/production` (专业生产监控).
- Professional workspace routes exist:
  - `projects.$projectId.scenes.tsx`
  - `projects.$projectId.scenes.$sceneId.tsx`
  - `projects.$projectId.production.tsx`
  - `projects.$projectId.edit.tsx`
  - `projects.$projectId.script.tsx`
  - `projects.$projectId.assets.tsx`

### Creation domain

- `app/creation/service.py` `CreationService` (S1/S2 manual path).
- `StartProjectResult`, `ConfirmPlanResult`, `CreationStateResult` dataclasses.
- `confirm_plan_and_materialize()` gated by `require_legacy_execution_allowed()`.

### Legacy gate

- `app/director/legacy_guard.py` `require_legacy_execution_allowed(session, project_id, action)`.
  - Fails closed (raises `DIRECTOR_COMMAND_REQUIRED`) when a `DirectorWorkflowRun`
    exists for the project.
  - Wired into: creation (`confirm_plan`), characters, generations, production,
    shot_ops, execution.shot_review, providers.generation_service.

### Workflow Template foundation

- `app/director/production_templates.py`
  - `DIALOGUE_POST_DUB_SHOT_V1 = "dialogue-post-dub-shot-v1"`
  - `QUALITY_POLICY_V1 = "live-dialogue-quality-v1"`
  - `dialogue_post_dub_definition(character_reference_keys, primary_character_reference_key, context)`
  - Provider-neutral graph (keyframe → identity_review → video → video_drift_review →
    voice/subtitle → composite → continuity_review).
- `app/execution/shot_pipeline.py` — separate `shot_pipeline_definition` /
  `SHOT_PIPELINE_TEMPLATE_KEY` used by `WorkbenchExecutionService`.

### Execution / Reference planning

- `app/production/execution_plan.py`
  - `WorkbenchExecutionPlan` (P4-01), `PlannedReference`, `PlanDelivery`
    (`exact|approximate|unsupported`), `CapabilityGap`, `ControlTranslation`,
    `fingerprint_plan`.
- `app/production/reference_intents.py`
  - `ShotReferenceIntent`, `compile_references` (P4-02) — classifies every reference
    against manifest input slots, **never silently drops unsupported refs**.
- `app/production/workbench_execution.py`
  - `WorkbenchExecutionService` (P4-05) — one Professional shot execution without
    any legacy gate. Builds plan → freezes → resolves graph → queues NodeRun.
- `app/providers/model_resolution.py` `ExecutionModelResolver`.
- `app/providers/capabilities.py` `Capability`.
- `app/providers/manifest.py` `ModelManifest`, `InputSlotSpec`.

### Consistency

- `app/consistency/identity_review.py`, `video_drift.py`, `continuity.py`,
  `identity_policy.py`.

### Editing

- `app/editing/adapter.py`, `app/editing/timeline_builder.py`.

### Data model already supports long-form

- `Project → Episode → Scene → Shot` (with `scene_number`, `shot_number`,
  `sort_order`, `duration_seconds`).
- `Scene.design_state` JSON and `Shot.director_state` JSON exist.
- `Asset`, `AssetVersion`, `AssetVersionReference`, `Character`,
  `CharacterReference` exist.

---

## 3. Partial (exists but incomplete for Workflow Expansion)

| Area | Current state | Gap |
| --- | --- | --- |
| ExperienceMode | `ExperienceMode` = `{QUICK, WORKBENCH}` in `app/shared/enums.py`; `start_project` defaults to `ExperienceMode.QUICK`. It is a persisted project field. | Not yet proven to be presentation/autonomy-only; not renamed to `GUIDED/PROFESSIONAL/AUTOMATED`. |
| Production template library | Only `dialogue-post-dub-shot-v1` (one mature template) + `shot_pipeline_definition`. | No formal registry, no versioned contract, no eligibility resolver, no template-library breadth. |
| Multi-character | `ShotReferenceIntent`/`PlannedReference` use `binding_id` + `purpose`; the dialogue template docstring states "only the shot's primary on-screen character is injected into the current single-reference image compiler". `StoryboardShot` historically `characters: max 2`. | No `ShotCharacterParticipation` value object; per-character subject binding not enforced through planning → provider. |
| Reference capability | `compile_references` classifies per reference and fail-closes on `unsupported`; `PlanDelivery` exists. | No `multi_character_reference` / `subject_binding` capability expression in manifest; no "primary collapse" negative gate. |
| Complex shot | `Shot.shot_type`, `camera_move`, `duration_seconds`, `director_state`. | No `ShotDirectorIntent`, `ShotComplexityAssessment`, no risk strategy. |
| Layered planning | `Episode/Scene/Shot` ORM + creation service materialization; `shooting_service`/`creative_service` for single short-dialogue contract. | No `EpisodePlanPayload` / `ScenePlanPayload` / `SceneStoryboardPlanPayload` typed contracts; duration/shot-count still tied to single-short contract in places. |
| Scene orchestration | `WorkbenchExecutionService` is shot-scoped. | No scene-batch boundary, no `prepare scene` / `execute selected shots` / scene production status. |
| Cross-scene continuity | `app/consistency/continuity.py` exists for shot/short continuity. | No `SceneContinuityContext` / `SceneContinuityReport`, no AssetVersion freeze across scene resume, no scene-level PASS/WARNING/BLOCKED. |
| Editing assembly | `editing/adapter.py`, `timeline_builder.py`. | Not proven to compose `Episode → Scene → Shot` timeline with per-clip `episode_id/scene_id/shot_id/artifact lineage`. |

---

## 4. Missing (must be added)

### WF2 Workflow Template Framework

```text
backend/app/director/workflows/
    __init__.py
    contracts.py    # WorkflowTemplateSpec / Resolution / Input / Output / Eligibility
    registry.py     # register / get / list / eligible / validate
    resolver.py     # WorkflowTemplateResolver
    library.py      # template definitions (dialogue, monologue, two-character, action, establishing, montage)
```

- `WorkflowTemplateSpec` (typed): `template_key`, `template_version`, `scope`,
  `display_name`, `intent_tags`, `supported_mediums`, `supported_character_count`,
  `duration_range`, `required_reference_roles`, `optional_reference_roles`,
  `required_capabilities`, `quality_policy_id`, `repair_policy_id`, `graph_factory`,
  `eligibility_policy`.
- `WorkflowTemplateResolution` (typed): `requested_template_key`, `resolved_template_key`,
  `template_version`, `status` (`RESOLVED`/`UNAVAILABLE`), `source`, `reason`,
  `contract_hash`.
- Registry is provider-neutral, deterministic, version-aware. No Provider request,
  credential access, model selection, or fallback model.

### WF1 Canonical Path closure

- Redefine `ExperienceMode` as presentation/autonomy policy (not execution chain).
- New professional projects: `legacy materialization calls = 0`.
- Extract legacy confirm behind explicit `recovery-only` API posture.
- New gate tests asserting new professional project → legacy call count = 0.

### WF5–WF10 contracts

```text
ShotCharacterParticipation
ShotDirectorIntent
ShotComplexityAssessment
EpisodePlanPayload
ScenePlanPayload
SceneStoryboardPlanPayload
SceneContinuityContext
SceneContinuityReport
```

### WF11

- Long-form navigator / scene status / template indicator / multi-character binding UI /
  editing assembly for `Episode → Scene → Shot`.

---

## 5. Drift

| Item | Drift |
| --- | --- |
| Single `ExperienceMode` | Rename is explicitly deferred; must at least prove UX/autonomy-only semantics for new paths. |
| `production_templates.py` old docstring | States "only the shot's primary on-screen character is injected". This is a real multi-character semantic hole to close (WF5/WF6). |
| `shot_pipeline_definition` vs `dialogue_post_dub_definition` | Two graph definitions exist. Must land on one template registry and avoid duplicate truth (WF3). |
| `CreationService.ALLOWED_MATERIALIZATION` | Historical S1/S2 manual-materialization allow-list. Must not leak into new professional path. |

---

## 6. WF0 Gate

> **Gate: Do not re-implement existing capability.** The audit above confirms the
> current `dev` already contains a working Canonical Professional Path (frontend),
> provider-neutral dialogue template, professional workbench execution, reference
> compiler with fail-closed reference handling, and the long-form data model.

Workflow Expansion therefore begins from the already-correct foundation and must
**add** the missing contracts/registry/orchestration rather than rebuild them.

```text
WF0 BASELINE = OK
```

---

## 7. Audit artifacts referenced

- `app/creation/service.py`
- `app/director/production_templates.py`
- `app/director/legacy_guard.py`
- `app/director/workflows/` (to be created — WF2)
- `app/production/execution_plan.py`
- `app/production/reference_intents.py`
- `app/production/workbench_execution.py`
- `app/shared/enums.py` (`ExperienceMode`)
- `frontend/src/routes/projects.$projectId.quick.tsx`
- `frontend/src/routes/*` (scenes / production / edit / script / assets)
