# WF13-01 — Real Provider Workflow Golden Report

**Document type:** Real paid-provider workflow golden evidence (Part A)
**Head:** `82d5ee53ea00fb84ef43911597c7d63e8f29411a` (dev baseline)
**Provider:** Agnes (image + video), in scope for dev/Golden per the execution plan
**Evidence file:** `WORKFLOW_V1_5_REAL_PROVIDER_GOLDEN.json`
**Scope:** 1 project / 1 episode / 2 scenes / 5 shots / 2 recurring characters / 2 locations

This closes the WF12 caveat: the real paid-provider workflow golden on the
multi-shot / multi-scene structure, plus the authoritative **fail-closed**
multi-subject gate that was previously only advisory.

---

## 1. What was proven

### 1a. Real paid-provider production chain (action shot)

The action shot (scene 2, wide, single visible character) ran the full canonical
professional path end-to-end against the real Agnes provider:

```
→ ExecutionModelResolution (keyframe + video bindings, account_verified)
→ real Agnes request
→ ProviderOperation (keyframe.generate + video.generate)
→ Artifact (image/png keyframe + video/mp4)
```

Evidence in the JSON: 2 `succeeded` provider operations
(`keyframe.generate`/`agnes-image-2.1-flash`,
`video.generate`/`agnes-video-v2.0`), 7 artifacts, the video produced a
`video/mp4` (967 KB, 5 s). `paid_provider_calls = 2` — the two paid calls are
keyframe + video for this single shot. Cost reported by the provider is
`null` (`cost_status: not_reported`), so no fabricated cost figure is recorded.

### 1b. Multi-subject fail-closed gate (two-character shot)

The two-character shot (scene 1, "two shot", 2 visible characters) was frozen
with an explicit participation plan (both characters visible) and the
`two-character-dialogue-v1` workflow template. The dispatch-time gate — newly
wired into the authoritative execution boundary — committed the keyframe run
terminally `failed` with `MULTI_SUBJECT_UNSUPPORTED` and **zero**
ProviderOperations:

```
status: EXACT / APPROXIMATE / UNSUPPORTED  → UNSUPPORTED (Agnes reference_image max = 1)
Provider POST = 0                          → provider_post_count = 0
reason: "model supports 1 subject reference(s) but the shot requires 2;
        multi-character identity cannot be preserved"
```

This is the authorized fail-closed outcome: Agnes cannot preserve two subject
references in one image (`reference_image` slot caps at `max:1`), so posting a
single-reference frame would prove only character A survived. The gate forbids
that ("禁止只发角色 A 后宣称 multi-character PASS"). No paid provider call was
made for this shot.

### 1c. Frozen template identity

Recorded in the evidence: `two-character-dialogue-v1` @ `1.0.0`,
`contract_hash a42277423ffb20f7dbff736967e35c6f4f393e800367366ab5412f6377972b2b`,
with the two-character participation bindings frozen onto the shot.

---

## 2. New code landed for this gate

The fail-closed capability gate existed only in the planning/read layers and was
**not enforced at dispatch** — a 2-visible-character shot would have silently
sent exactly 1 reference. WF13-01 closes this:

- `app/director/workflows/reference_capability.py` — added pure, single-sourced
  dispatch-time decisions: `visible_subject_count_from_snapshot`,
  `max_subject_references_from_catalog_manifest`, `dispatch_capability_gate`.
- `app/execution/product_path.py` — wired the gate into
  `_execute_unified_media_node_run` for `node_type == "keyframe"`: if the shot's
  frozen participation plan requires more subjects than the resolved catalog
  manifest allows, the run is committed terminally `MULTI_SUBJECT_UNSUPPORTED`
  and the provider call is never issued. The gate reads the authoritative
  `Shot.director_state`, never the minimized snapshot; a non-UUID/missing
  `shot_id` is a no-op (no plan to gate). Resume of an already-accepted task is
  never re-gated (the block only runs on a fresh submission branch).
- `app/api/v1/workflow_planning.py` — participation-plan / workflow-template
  freeze endpoints now persist (`session.commit()`), fixing a bug where the
  frozen plan never reached `Shot.director_state`.
- `app/providers/adapters_v2.py` + `app/providers/agnes.py` — fixed the
  legacy bridge compiler-evidence envelope so `/characters/lead` (the only API
  path to create a `Character` row) can compile an image request. The Agnes image
  compiler now publishes `effective_common_options` alongside the
  transformation list, and the audit allowlist now accepts the bounded `size`
  field and its documented reason code.

### Why this gate is authoritative

The reference compiler is the only boundary that knows the resolved model's
capability slot. `assess_multi_character_capability` (planning) is advisory;
`dispatch_capability_gate` (execution) is the boundary that raises before any
Provider POST. Both single-source the limit from the catalog manifest's
`reference_image.max`.

---

## 3. Honest limits

- **`unsupported_capability_shots: 0` in the `workflow-overview` read model.**
  That aggregate endpoint does not resolve per-shot workspace manifests, so its
  planning-only `capability_assessment` stays `null`. The authoritative fail-closed
  evidence is the dispatch gate's `MULTI_SUBJECT_UNSUPPORTED` keyframe run, which
  IS captured. The overview counter is a display convenience, not the gate.
- **Cost is `not_reported`.** Agnes reports cost as `null`; no cost figure is
  invented. `paid_provider_calls` counts operations that reached a terminal
  provider state, not a dollar amount.
- **Formal selection stops at human review.** The action shot's `approve` was
  blocked by the legitimate `APPROVE_GATE` (identity_review needs human, plus
  downstream voice/subtitle/composite are unrun). This is correct workflow
  behavior — the golden records the human-review gate rather than forcing an
  approve past it.
- **Character lead generation is transient 5xx-fragile.** The `/characters/lead`
  canonical image call intermittently returns `PROVIDER_UNAVAILABLE` (upstream
  Agnes 5xx). The golden retries with backoff; the evidence captured is from a
  successful run.
- **Evidence is clean (`dirty=false`) at commit `d3d945f`.** The gate code was
  committed first, then the evidence re-captured from the completed project run.
  The work is reproducible from a committed baseline.

---

## 4. Conclusion

| Check | Result |
| --- | --- |
| Real paid provider chain (keyframe → video → artifact) | PASS |
| Frozen template identity (key/version/hash) | PASS |
| Multi-subject capability gate (UNSUPPORTED → POST=0) | PASS (authoritative, at dispatch) |
| No silent single-primary collapse | PASS (gate forbids it) |
| Cost honesty | PASS (records `not_reported`, no fabricated figure) |
| Formal selection | Stops at human review (correct) |

```text
PROFESSIONAL_WORKFLOW_FRAMEWORK_V1_5 = NOT YET FROZEN (WF13-02/03 remain)
REAL_PROVIDER_MULTI_SUBJECT_GATE = ENFORCED (dispatch-time, fail-closed)
```

**Status:** WF13-01 evidence captured. Next: WF13-02 (wire-visible UI) →
WF13-03 (freeze gate).
