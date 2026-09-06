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
- Before implementation, no `ExecutionModelResolver` or `ExecutionModelResolution` existed; the implementation below closes this MS1 gap.

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


## Implementation Result (2026-08-26)

- **Status：COMPLETED**。
- 新增 `backend/app/providers/model_resolution.py`，提供唯一 typed、非 ORM 的 `ExecutionModelResolution` 与 `ExecutionModelResolver`；按 request override → project slot → workspace slot → system default 的 slot 级顺序解析。
- Professional `ModelSelectionService` 已消费该 resolver；Profile 明确选择的 X 在没有可用 concrete binding/catalog 时返回 `UNAVAILABLE` / `MODEL_BINDING_UNAVAILABLE`，不再静默切换 Legacy Y。
- `backend/app/execution/product_path.py` 在 compiler/runtime 前冻结并写入 `NodeRun.input_snapshot` 和 `ProviderOperation` 的脱敏 resolution；恢复路径仍消费既有 ProviderOperation，不新增 Generation/Runtime/Worker 真相。
- 未实现且明确留给 MS5-IDENTITY 的 credential / connection immutable revision；当前 typed result 不写入 secret 或 credential 内容。

## Acceptance Evidence

- Resolver focused tests：`backend/tests/unit/test_execution_model_resolution.py`，5 passed。
- Selection regression：`backend/tests/unit/test_model_selection.py`，9 passed；含 X unavailable + Legacy Y 存在时 fail-closed。
- Professional unified execution：`backend/tests/unit/test_unified_path.py`，20 passed；含 NodeRun snapshot、ProviderOperation resolution 与 zero Provider submission proof。
- Combined model-profile / selection / resolver regressions：32 passed。
- Backend unit suite：676 passed，1 warning；PostgreSQL snapshot integration contract已新增为 `backend/tests/integration/test_execution_model_resolution_pg.py`，在未启用/不可达 PostgreSQL 时按仓库规则 skip。
- Static checks：targeted `ruff`、`mypy` and `git diff --check` passed；active seven-plan reference verifier and directory compliance passed。

## Drift Closed / Deferred

- 已关闭：Professional execution 中 Profile X → Legacy Y 的 silent fallback；selection 与 snapshot 的多入口分歧（统一由 `ExecutionModelResolver` 供给）。
- 仍待后续合同：MS2 strict slot/media/cardinality validation；MS3 ordered references；MS4-LITE mode identity；MS5-R / MS5-IDENTITY execution identity and immutable revisions。
