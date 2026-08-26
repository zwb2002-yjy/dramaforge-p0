# Task: MS1-R-AND-MS1-C-EXECUTION-MODEL-RESOLUTION

## Read first

- [`../README.md`](../README.md)
- [`../CURRENT_MODEL_SUPPLY_DRIFT.md`](../CURRENT_MODEL_SUPPLY_DRIFT.md)
- `06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` §§ 5–6, 14–15, 19–21;
- `07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` §§ 6–7, 15–17;
- `04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md` and `05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md` MS1;
- current `model_profiles/resolver.py`, `selection.py`, `workspace_router.py`, `runtime.py`, product execution and their focused tests.

## Current Evidence

- PLAN-00 / PLAN-01 internalized the seven-plan authority and removed old active planning routes;
- [`../CURRENT_MODEL_SUPPLY_DRIFT.md`](../CURRENT_MODEL_SUPPLY_DRIFT.md) proves the concrete X→Y fallback and multiple model-decision entry points;
- no `ExecutionModelResolver` or `ExecutionModelResolution` exists.

## Target

Create one typed non-ORM `ExecutionModelResolution` and one `ExecutionModelResolver` for Professional execution. Resolution priority is request override → project profile **slot** → workspace profile **slot** → system default. An explicit/project-selected X that cannot be concretely bound must return stable `UNAVAILABLE` / `MODEL_BINDING_UNAVAILABLE`; it must not execute Legacy Y or submit a Provider request.

The Professional execution planner consumes and snapshots that result; downstream selection/runtime code receives the frozen concrete decision and must not independently choose another model.

## Allowed

- `backend/app/providers/` resolution/selection/profile modules;
- Professional execution planning path and narrow schemas/types necessary to transport a frozen result;
- focused unit/integration tests and a migration only if a real persisted contract requires it.

## Forbidden

- no parallel Generation/Runtime/Worker abstraction;
- no automatic fallback in formal production;
- no credential or connection revision implementation yet (MS5-IDENTITY owns it);
- no Provider calls, no secrets in typed results/snapshots, no Provider-name branching in business/UI code;
- do not weaken old compatibility tests or delete legacy paths.

## Acceptance

- tests cover explicit override, project slot, workspace slot, system default, project slot absent, X unavailable with legacy Y available, and zero Provider submissions on failure;
- the typed result includes requested/resolved model, source, status/reason, binding/connection/catalog/manifest identity, capability, mode and native options;
- NodeRun snapshot includes the redacted resolution; execution does not reselect a model;
- existing model-profile, selection, Provider and recovery regressions pass.

## Tests

- focused new resolver and Professional execution tests;
- `ruff`, `mypy`, targeted unit tests, PostgreSQL integration for changed persistence, frontend typecheck/tests only if API types change.
