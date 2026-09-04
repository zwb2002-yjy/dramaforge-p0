# DramaForge Workflow Expansion — Final Report

**Document type:** Final Report (WF12)
**Program:** Professional Program v2 — Workflow Expansion
**Design:** `DRAMAFORGE_WORKFLOW_EXPANSION_DESIGN.md`
**Execution plan:** `DRAMAFORGE_WORKFLOW_EXPANSION_IMPLEMENTATION_PLAN.md`

---

## 1. Header

| Field | Value |
| --- | --- |
| Start HEAD | `18dfc51ddb2028602a3ebcf3c14c9b3a6dda4bbc` |
| End HEAD | `e44d7afc5cd9a38e43f131d4e2d3611810214698` |
| Branch | `dev` |
| Migration | HEAD unchanged `20260827_0049` (no schema migration required) |
| Backend unit tests | `889 passed` (baseline `831` → `+58` new) |
| ruff | `All checks passed` |
| mypy | `Success: no issues found in 230 source files` |
| Baseline audit | `docs/reviews/WORKFLOW_EXPANSION_BASELINE.md` |

No database schema change was needed: every new contract is stored in the
existing `Scene.design_state` / `Shot.director_state` JSON columns and the
`NodeRun.input_snapshot` / `GraphVersion` definition, per the design's
"prefer not to add tables" strategy. Templates are code-versioned by
`template_key + template_version + contract_hash`, as recommended.

---

## 2. WF0–WF12 Status

| WF | Status | Evidence |
| --- | --- | --- |
| WF0 Baseline / Drift Audit | ✅ | `WORKFLOW_EXPANSION_BASELINE.md` |
| WF1 Canonical Path Closure | ✅ | `ExperienceMode` redefined as presentation/autonomy-only; `start_project` defaults to `WORKBENCH`; legacy `confirm_plan` is recovery-only for historical `QUICK` projects; G-WF-01 architecture gate test (`legacy call count = 0`) |
| WF2 Template Contract + Registry | ✅ | `app/director/workflows/contracts.py` `registry.py` `resolver.py` |
| WF3 Migrate dialogue template | ✅ | `library.py` registers `dialogue-post-dub-shot-v1`; registry factory reproduces the existing graph byte-for-byte |
| WF4 Template Library Expansion | ✅ | 6 templates: dialogue + `single-character-monologue-v1`, `two-character-dialogue-v1`, `action-motion-shot-v1`, `establishing-reaction-insert-v1`, `montage-sequence-v1`; each has a distinct contract hash / topology / policy |
| WF5 Multi-character Planning | ✅ | `ShotCharacterParticipation` / `ShotParticipationPlan`; max 4 visible-controlled; DB cross-workspace binding validation; `StoryboardShot.characters` cap relaxed to 4 (template-driven) |
| WF6 Reference / Capability Gate | ✅ | `assess_multi_character_capability` EXACT/APPROXIMATE/UNSUPPORTED; UNSUPPORTED → fail closed (Provider POST=0); APPROXIMATE only via accepted registered strategy; reference compiler never silently drops B; per-character `MultiCharacterIdentityReport` (no silent aggregate pass) |
| WF7 Complex Shot Intent/Risk | ✅ | `ShotDirectorIntent` / `ShotComplexityAssessment`; deterministic SINGLE_PASS/STAGED/NEEDS_EXPERIMENT/UNSUPPORTED |
| WF8 Episode/Scene Layered Planning | ✅ | `EpisodePlanPayload` / `ScenePlanPayload` / `SceneStoryboardPlanPayload`; duration owned by Production Profile; platform safety limits; idempotent `materialize_episode_plan` / `materialize_scene_storyboard` |
| WF9 Scene-level Orchestration | ✅ | `SceneProductionState` / `SceneProductionStatus` read model; scene = batch boundary; failure isolation (G-WF-09); `SCENE_CONCURRENCY_LIMIT=4` |
| WF10 Cross-scene Continuity | ✅ | `SceneContinuityContext` / `SceneContinuityReport`; freeze/resume uses originally frozen AssetVersion (G-WF-08); PASS/WARNING/BLOCKED |
| WF11 Long-form editing assembly | ✅ backend | `build_edit_session_for_project` — Episode→Scene→Shot timeline with per-clip `episode_id/scene_id/shot_id/artifact_id` lineage |
| WF12 Golden Gate | ✅ deterministic | `test_workflow_expansion_golden.py` (canonical path + registry/freeze + materialization + multi-char gate + complexity + scene status + continuity + editing assembly + NEG-01) |

---

## 3. Commits (WF split, no monolithic commit)

```text
148c56f fix(workflow): close canonical professional path          (WF0+WF1)
2836e1f feat(workflow): add versioned workflow template contracts (WF2)
d052bf1 refactor(workflow): register dialogue production template (WF3)
ca80698 feat(workflow): add baseline shot template library        (WF4)
aa1ad11 feat(director): add multi-character shot participation    (WF5)
8c495da feat(execution): enforce multi-character reference integrity (WF6)
93a4fcc feat(director): add complex-shot planning strategy        (WF7)
321926e feat(creative): add episode and scene layered planning    (WF8)
d50aff9 feat(production): orchestrate production by scene         (WF9)
e841322 feat(continuity): freeze cross-scene continuity context   (WF10)
e44d7af feat(frontend): expose long-form workflow controls       (WF11+WF12)
```

---

## 4. Templates Implemented

```text
dialogue-post-dub-shot-v1          (migrated, unchanged graph/quality)
single-character-monologue-v1      (no timed subtitle track)
two-character-dialogue-v1          (2 subject refs + 2 voice tracks)
action-motion-shot-v1              (no voice; motion/anatomy repair)
establishing-reaction-insert-v1    (no identity review; env ref primary)
montage-sequence-v1                (scene scope)
```

Each template carries a genuine contract difference (reference roles, graph
topology, quality/repair policy, capability requirements, scope). A distinct
`contract_hash` (over the frozen semantic contract, excluding the
`graph_factory` callable) guarantees execution reproducibility.

---

## 5. Evidence per Architecture Gate

| Gate | Evidence |
| --- | --- |
| G-WF-01 Canonical Path | `test_workflow_expansion_canonical_path.py` — new professional project → legacy confirm refused, NodeRun/ProviderOperation/Outbox = 0 |
| G-WF-02 Single Execution Truth | All templates are provider-neutral graph definitions resolved via the registry; production still flows through ProductionGraph → NodeRun → ProviderOperation → Artifact. |
| G-WF-03 Template Freeze | `template_key/version/contract_hash` frozen into `Shot.director_state` and available for `NodeRun.input_snapshot`; retry/resume reuses the frozen identity |
| G-WF-04 No Silent Fallback | `test_workflow_template_contracts.py` + NEG-01: explicit ineligible template → `UNAVAILABLE`, no substitution |
| G-WF-05 Multi-character Integrity | `ShotParticipationPlan` preserves all visible subject bindings; 2-char shot keeps A + B references |
| G-WF-06 Unsupported Reference | `test_workflow_reference_capability.py`: A+B required, model max=1 → `UNSUPPORTED`; reference compiler marks the excess reference unsupported, not dropped |
| G-WF-07 Long-form | `test_workflow_layered_planning.py` + golden: 1 project, episodes, 2+ scenes, 6+ shots; independent production/review/resume/editing |
| G-WF-08 Continuity Freeze | `test_workflow_continuity.py`: Scene 1 frozen AssetVersion reused on resume even after project moved to a newer version |
| G-WF-09 Scene Failure Isolation | `test_workflow_scene_orchestration.py`: a blocked scene does not contaminate a sibling scene |
| G-WF-10 Legacy Recovery | WF1: historical `QUICK` project remains recoverable via the legacy confirm path; new professional projects are blocked |

---

## 6. Multi-character / Long-form evidence (deterministic

```text
2-character participation     identified
Multi-character capability     UNSUPPORTED when model cannot bind both (POST=0)
Reference compiler             no silent primary collapse
Complex-shot strategy          STAGED / NEEDS_EXPERIMENT from deterministic rules
Scene status                   READY / PRODUCING / BLOCKED / COMPLETE (read model)
Continuity freeze              PASS / WARNING / BLOCKED
Editing assembly               episode → scene → shot ordered timeline, read-only lineage
```

---

## 7. Known Limitations

1. **Real paid-provider golden run not executed in this session.** The golden
   tests run the full Orchestration/contract path with deterministic/fake
   provider verification (no paid HTTP). The representative real-provider
   `Agnes` keyframe/video golden remains an operator step requiring live
   credentials and budget approval. It is NOT covered by the automated suite.
2. **Frontend Professional UX is not rebuilt.** WF11's long-form navigator,
   scene-status indicator, template/capability indicator, multi-character
   binding display and long-project progress panel are **not** wire-visible in
   the current React app. Only the backend editing-assembly is implemented.
   The design calls this a separate "Professional UI / UX Rebuild" phase.
3. **No new ORM tables** were added (per design preference). Once heavy
   read-patterns or audit needs emerge (e.g. a `WorkflowTemplateCatalog`), a
   separate migration is required.
4. **Staged-strategy allowlist** is minimal (two strategies); a full
   strategy-registry and per-user approval flow is deferred.
5. **`ExperiencedMode` rename** to `GUIDED/PROFESSIONAL/AUTOMATED` is deferred
   (the plan explicitly allows it); the existing `QUICK/WORKBENCH` enum is
   documented as presentation/autonomy-only.

---

## 8. Deferred Work

```text
Real Agnes keyframe/video golden run            (requires paid live credentials)
Professional UI / UX rebuild (WF11 frontend)     (separate phase)
WorkflowTemplateCatalog ORM                      (only when query/audit requires)
Full staged-strategy registry + user acceptance   (WF6 extend)
ExperienceMode enum rename                        (compat, optional)
```

---

## 9. Gate Conclusion

```text
WORKFLOW_EXPANSION_GATE = PASSED (code/deterministic)
READY_FOR_CREATIVE_CAPABILITY_LIBRARY = YES
```

> ⚠️ Caveat: the code/deterministic gate passes (889 unit tests, ruff/mypy
> clean, no migration drift). The **real paid-provider golden run** is the only
> remaining operator-verified step before the workflow can be declared
> `Professional Workflow Framework V1.5 = COMPLETE` without caveat. It is
> recommended to run the representative Agnes golden (1 two-character shot +
> 1 per scene representative shot) under budget approval before user sign-off.
