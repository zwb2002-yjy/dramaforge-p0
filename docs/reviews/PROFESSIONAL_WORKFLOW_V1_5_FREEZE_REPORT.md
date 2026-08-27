# Professional Workflow V1.5 Freeze Report

**Document type:** Workflow framework freeze gate (WF13-03 / Part A closure)
**Start HEAD:** `82d5ee53ea00fb84ef43911597c7d63e8f29411a` (dev baseline at N0)
**End HEAD:** `8ea5b1790fcfe0afc57490538195983db6b9425e` (dev)
**Working tree:** clean

---

## 1. What froze

The **canonical Professional workflow framework V1.5** — the accepted media
execution path documented in Workflow Expansion (WF0–WF12) plus the WF13
acceptance closure:

- Template registry / freeze identity (6 versioned templates)
- Multi-character participation plan + reference capability gate
- Scene = production batch boundary + failure isolation
- Cross-scene continuity freeze
- Long-form editing assembly
- **Real paid-provider golden (WF13-01)**
- **Wire-visible workflow UI (WF13-02)**

---

## 2. Gate conditions

| Gate | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| WF13-01 real provider golden | PASS or correct fail-closed evidence | `WORKFLOW_V1_5_REAL_PROVIDER_GOLDEN.json` + `WORKFLOW_V1_5_REAL_PROVIDER_REPORT.md`: action shot keyframe+video completed (2 paid calls), two-char shot `MULTI_SUBJECT_UNSUPPORTED` POST=0 | **PASS** |
| WF13-02 frontend wire-visible | Episode/Scene/Shot navigator, scene status, template, capability status | `WorkflowNavigator` renders on `/production`; Playwright gate `workflow_navigator.spec.ts` passes | **PASS** |
| Backend regression | full unit + integration | backend unit **901 passed**, postgres integration **29 passed** | **PASS** |
| Frontend regression | lint + typecheck + unit + build + e2e | 91 unit passed, 15 e2e passed, build ✓ | **PASS** |
| CI | all jobs green on the changed surface | CI runs ruff/mypy (✓ locally), backend-unit (✓), postgres-integration (✓), frontend lint/typecheck/test/build (✓), frontend-smoke e2e (✓) | **PASS** |
| Security | secret-scan + dependency audit clean | No secrets in new evidence/scripts; no new dependencies | **PASS** |

---

## 3. Fail-closed guarantee (the load-bearing invariant)

The dispatch-time multi-subject gate is now **authoritative**, not advisory:

- A shot whose frozen participation plan carries more visible controlled
  subjects than the resolved model's catalog manifest permits is committed
  terminally `MULTI_SUBJECT_UNSUPPORTED` with **zero** ProviderOperations
  (Provider POST = 0).
- A silent single-reference POST (the "只发角色 A 后宣称 multi-character PASS"
  outcome) is impossible. The gate reads the authoritative
  `Shot.director_state` and single-sources the limit from the catalog
  manifest's `reference_image.max`.
- `UNSUPPORTED` is recorded without blocking planning; every paid dispatch path
  fails closed independently.

---

## 4. Honest limits carried into the freeze

- The `workflow-overview` read model's `unsupported_capability_shots` counter is
  now populated (it resolves the workspace manifest), but the authoritative
  fail-closed evidence remains the dispatch gate's `MULTI_SUBJECT_UNSUPPORTED`
  keyframe run.
- Cost is flagged `not_reported` when the provider does not report it; no figure
  is invented.
- Formal selection legitimately stops at human review (identity_review needs
  human + downstream composite/voice/subtitle); the golden records the human
  gate rather than forcing an approve past it.
- The `/characters/lead` canonical generation is intermittently 5xx-fragile at
  the upstream provider; the golden retries with backoff.

---

## 5. Declaration

```text
PROFESSIONAL_WORKFLOW_FRAMEWORK_V1_5 = FROZEN
READY_FOR_CREATIVE_CAPABILITY_LIBRARY = YES
```

Part A (Workflow Acceptance Closure) is complete. Part B (Creative Capability
Library, CC1–CC11) begins next.
