# DramaForge Creative Capability Baseline / Drift Audit (N0)

**Document type:** Baseline audit before Part A/B execution
**BASE_HEAD:** `82d5ee53ea00fb84ef43911597c7d63e8f29411a` (`dev`)
**Working tree:** clean at audit time
**MIGRATION_HEAD:** `20260827_0049_edit_sessions` (no new migration required by
this plan unless a new ORM table becomes strictly necessary — current strategy:
store in existing JSON state columns)
**Backend suite:** `895 passed, 23 skipped` (backend/.venv, pytest -q) — green
**Design docs:** `D:\DRAMAFORGE_NEXT_PHASE_CREATIVE_CAPABILITY_DESIGN.md`,
`D:\DRAMAFORGE_NEXT_PHASE_CREATIVE_CAPABILITY_IMPLEMENTATION_PLAN.md`

---

## 1. Already done (do not rewrite)

### Workflow Expansion (WF0–WF12) — all landed on dev

- Canonical professional path closed; legacy confirm is recovery-only.
- `app/director/workflows/` package: contracts (frozen `WorkflowTemplateSpec`
  + `contract_hash` over the semantic subset excluding `graph_factory`),
  registry, fail-closed resolver (G-WF-04), library of 6 versioned templates:
  dialogue-post-dub-shot-v1, single-character-monologue-v1,
  two-character-dialogue-v1, action-motion-shot-v1,
  establishing-reaction-insert-v1, montage-sequence-v1.
- Multi-character planning: `ShotParticipationPlan`, per-character reference
  integrity, DB cross-workspace validation; max 4 visible-controlled.
- Reference/capability gate: `assess_multi_character_capability` EXACT /
  APPROXIMATE / UNSUPPORTED; UNSUPPORTED → Provider POST = 0 (fail-closed);
  APPROXIMATE only via accepted registered staged strategy; no silent primary
  collapse in the reference compiler.
- Complex-shot assessment: deterministic SINGLE_PASS/STAGED/NEEDS_EXPERIMENT/
  UNSUPPORTED from `ShotDirectorIntent`.
- Layered planning + materialization service: `materialize_episode_plan` /
  `materialize_scene_storyboard` create real Episode/Scene/Shot rows
  idempotently and freeze `workflow_template_key` into `Shot.director_state`.
  **No REST surface yet** — invoked from tests only. → feeds WF13-01/02.
- Scene orchestration read model: `scene_production_status()` returns
  READY/PRODUCING/... and failure isolation; scene = batch boundary.
- Cross-scene continuity: `SceneContinuityContext.freeze()` persisted into
  `Scene.design_state["continuity_context"]`; freeze/resume reuses the frozen
  AssetVersion.
- Long-form editing assembly: `build_edit_session_for_project` with per-clip
  lineage (read-only).
- Backend suite: 889→895 tests (latest run), ruff/mypy reported clean at last
  gate; CI + Security workflows exist (.github/workflows/ci.yml, security.yml).

### Evidence pattern for a paid golden exists and is proven

- `scripts/prove_professional_authenticated_evidence_runner.py` pattern via
  `scripts/prove_professional_agnes_golden.py`: authenticated API walk
  (bootstrap → register/login → CSRF → workspace → project → script import →
  canvas → Agnes connection + keyframe/video bindings verified → professional
  start (prompt/keyframe/identity_review) → wait for completed runs → video →
  single-character formal selection). Records only redacted metadata;
  credentials/signed URLs/raw provider payloads never written to disk.

---

## 2. Partially done (needs closure)

| Item | State | Closure |
| --- | --- | --- |
| Real provider workflow golden | Script pattern proven for single character, never run against the multi-shot/multi-scene structure required by WF13-01 (2 scenes / 6–8 shots / 2 recurring characters). | WF13-01 |
| Workflow UI wire-visible (WF11 frontend) | `SceneWorkspace.tsx` renders scene header (location/time), ShotStrip, design panel, trace; scenes list route exists. Missing: episode level, scene production status, template identity/version/capability status, multi-char bindings display, long-form progress. | WF13-02 |
| Quality policy is an opaque string | `quality_policy_id` flows template→batch payloads but has no registry/lookup; ProductionBatch stores it but nothing resolves it. | CC8 |
| `ShotDirectorIntent` serializers defined, not yet called | `complexity_director_state()` defined in shot_complexity.py; complexity assessment is deterministic but no service writes the intent into `Shot.director_state`. | CC7/CC9 |

### Partial: episode/scene materialization without API surface

`materialize_episode_plan` / `materialize_scene_storyboard` are service-layer
only; the deterministic WF12 golden drives them through direct session calls,
no REST surface exists yet. WF13-01 will drive everything through authenticated
REST like the P0 authenticated runner, so these become endpoint-backed
operations.

---

## 3. Missing (to be built in this plan)

1. **WF13-01** Real Agnes provider workflow golden on the multi-shot structure:
   2 scenes, representative two-character shot + second-scene action/dialogue
   shot, frozen template identity → capability gate → ExecutionModelResolution
   → ProviderOperation → Artifact → formal selection, evidence JSON+MD.
2. **WF13-02** Wire-visible Workflow UI: Episode/Scene/Shot navigator, scene
   production status badge, template key/version display, capability status
   (EXACT/APPROXIMATE/UNSUPPORTED), multi-character bindings list, long-form
   progress (formal/total shots, blocked scenes, review required). Read-only
   aggregation endpoints do not exist yet (`GET /projects/{id}/workflow-overview`
   etc.) — add read-model-only endpoints; no second persistence.
   Playwright spec must assert the real page wiring.
3. **WF13-03** Freeze report + declaration.
4. **CC1–CC9** `backend/app/director/creative_capabilities/` package entirely
   missing: contracts, registry/resolver, composer, 10 skills, 6 genre
   profiles, 10 style packs (+ VisualBiblePatch compiler), 6 shot-language
   packs (+ ShotDirectorIntentPatch compile), quality policy registry (5
   policies), CreativeCapabilityCompiler with user-override priority gate and
   provenance freeze.
5. **CC10** Director Agent integration (assistant context reads active
   capabilities; proposals carry capability provenance) + functional UI entries
   (Genre selector, Style selector, Active Skills; Shot inspector: Shot
   Language / Template / Quality Policy; Proposal panel: Used Skills / Used
   Style / Affected Fields).
6. **CC11** Creative golden (suspense composition compiling through to
   execution plan and representative real provider) + negative gates NEG-CC-01
   ..04 + final report.

## 4. Drift

1. **No drift in committed code vs the previous stage report**: HEAD equals the
   reported End HEAD `e44d7af`'s successor `82d5ee5` (report doc commit);
   working tree clean; migration head `20260827_0049` matches the report's
   declared `20260827_0049`.
2. **Test count moved from the report's 889 to 895 passed** (+23 skipped).
   Spot-check attribute: additional tests exist beyond the WF12 final report
   snapshot (the report counted its own run; later director-proposal/thread
   work landed inside the same commits before the audit snapshot). No failure,
   no scope drift introduced by this plan.
3. **`test_professional_agnes_golden.py` regression unit test** guards only the
   runner-script internals (snapshot polling); the actual paid run remains an
   operator step — unchanged since P0, as documented. This is the caveat that
   WF13-01 closes.
4. **Creative capabilities naming collision check**: `app.providers.capabilities`
   already exports `Capability`. The new package is named
   `app.director.creative_capabilities` (as designed) and MUST NOT shadow or
   re-export provider Capability vocabulary under conflicting names.

---

## 5. Conclusion

```text
WORKFLOW_EXPANSION_GATE            = PASSED (deterministic; prior stage)
PROFESSIONAL_WORKFLOW_FRAMEWORK_V1_5 = NOT YET FROZEN
READY_FOR_WF13_ACCEPTANCE_CLOSURE  = YES
READY_FOR_CREATIVE_CAPABILITY_LIBRARY = AFTER WF13 FREEZE
```

No completed Workflow Expansion work will be rewritten. Part A executes first
(WF13-01 → WF13-02 → WF13-03), then Part B (CC1 → CC11).
