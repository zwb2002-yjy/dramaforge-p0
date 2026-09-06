# Task: MS5-R-CONCRETE-MODEL-RUNTIME-RESOLUTION

## Read first

- [`../README.md`](../README.md)
- `04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md` §13 and the Phase 4 prerequisites;
- `05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md` §8 (MS5-01 through MS5 Gate);
- `06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` §13;
- `07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` §11;
- current `runtime.py`, `workspace_router.py`, `product_path.py`, Provider factories, bindings/catalog models and runtime tests.

## Current Evidence

- MS1–MS4 have established concrete `ExecutionModelResolution`, strict references and `mode_id` snapshots.
- `ProviderRuntimeResolver.resolve()` currently accepts `plugin`, `connection`, `binding` and `entry` but only uses the plugin/connection to construct generic runtime/compiler instances; it does not validate binding/catalog identity and does not expose the concrete model identity on the resolved runtime.
- Professional product execution manually loads a binding/catalog entry and then constructs runtime from the connection/plugin. The legacy `workspace_router.resolve_workspace_bridge()` still has a provider+media seed-manifest compatibility path; that path is not the Professional new execution chain and remains legacy-compatible.
- The runtime/compiler factories are intentionally generic and the existing compilers already receive `ProviderModelBinding.invoke_model_value` from the frozen selection plan; MS5 must connect and validate this identity without creating a new runtime abstraction.

## Target

Implement the bounded MS5-R slice:

1. Add `ProviderRuntimeResolver.resolve_runtime_for_model_binding(model_binding_id=...)` as the Professional entry point. It must load the concrete binding → connection → catalog entry, validate workspace/connection/catalog/provider/profile/media/lifecycle/manifest-hash consistency and require a non-empty `invoke_model_value`.
2. Return the existing `ResolvedRuntime` enriched with the concrete binding/catalog/model/invoke identity; do not create `ProfessionalRuntime`, `RuntimeV4` or another execution truth layer.
3. Update the Professional unified execution path to build runtime through the binding-based entry point and consume the returned concrete identity; leave the explicitly legacy workspace seed bridge intact and labeled as compatibility.
4. Prove two models under the same Provider do not select the first seed manifest: binding/catalog B resolves to B and the compiled wire model / operation identity remains B.
5. Keep MS5-IDENTITY out of scope: no immutable credential/connection revision migration yet, no credential storage changes, no real Provider calls.

## Allowed

- `backend/app/providers/runtime.py`, the narrow Professional call site in `backend/app/execution/product_path.py`, and explicit legacy-boundary comments/tests in `workspace_router.py` if needed;
- focused runtime/product tests and this Task Contract.

## Forbidden

- no new runtime/worker/generation abstraction;
- no provider-type/media-kind seed lookup in the Professional path;
- no credential or connection revision schema/service changes (MS5-IDENTITY);
- no Provider calls, no fallback to another binding/model, no broad Legacy workspace-router rewrite;
- do not change MS1–MS4 request, reference or mode contracts.

## Acceptance

- binding-based resolver loads and validates the selected concrete model/catalog identity;
- same Provider with two model bindings resolves the requested model B, uses B's `invoke_model_value`, and never chooses the first seed manifest;
- invalid catalog/provider/profile/hash/lifecycle/invoke identity fails closed before runtime creation;
- Professional unified path uses binding-based resolution while the legacy workspace bridge remains explicitly compatibility-only;
- `ProviderOperation.actual_model` / request summary and compiler wire model remain the frozen concrete model identity where those fields already exist;
- existing MS1–MS4, runtime, compiler, selection, recovery and full unit regressions pass.

## Tests

- new focused `tests/unit/test_runtime_model_resolution.py`;
- targeted `test_unified_path.py`, provider compiler/identity tests and full backend unit suite;
- `ruff`, `mypy`, active-plan/reference compliance and `git diff --check`.

## Drift

This Task closes concrete model-to-runtime resolution only. Immutable credential/connection revisions, restart identity and Phase 4 Merge Gate remain MS5-IDENTITY and later tasks.


## Implementation Result (2026-08-26)

- **Status：COMPLETED**。
- `ProviderRuntimeResolver.resolve_runtime_for_model_binding(model_binding_id=...)` 新增为 Professional runtime 入口：从 concrete `ProviderModelBinding` 读取并校验 Connection 与 Catalog revision，不按 provider/media 搜索 seed manifest。
- 新入口 fail-closed 校验 binding/connection enabled、workspace/connection/catalog/model/provider/profile/media 一致性、Catalog lifecycle、manifest hash 与 `invoke_model_value`；校验失败发生在 runtime factory 创建前。
- 既有 `ResolvedRuntime` 增加 binding、catalog、concrete model id、invoke model value 与 manifest hash，未新增 ProfessionalRuntime / RuntimeV4 / 第二套 Worker 或 Generation 真相。
- Professional unified execution path 已消费 binding-based resolver 返回的 concrete identity；旧 `workspace_router.resolve_workspace_bridge()` 的 provider/media seed lookup 保留并明确为 Legacy compatibility，不进入该路径。

## Acceptance Evidence

- Concrete two-model runtime identity：`backend/tests/unit/test_runtime_model_resolution.py`，8 passed；同一 Provider 的 model B 返回 model B / `wire-model-b`，catalog/provider/profile/hash/lifecycle/model/invoke 错误均在 runtime 创建前 fail-closed。
- Professional unified execution regression：`backend/tests/unit/test_unified_path.py`，20 passed。
- Backend unit suite：707 passed，1 warning。
- Static checks：`ruff check app tests alembic/versions` passed；`mypy app` passed；active seven-plan reference verifier and directory compliance passed；`git diff --check` passed。
- PostgreSQL snapshot contract from MS1 remains present; this Task did not add a migration, change credential/connection revisions, or invoke a real Provider.

## Drift Closed / Deferred

- 已关闭：Professional runtime 根据 provider_type + media_kind 选 first seed manifest；runtime resolver 对 concrete binding/catalog identity不校验；runtime result 不暴露 concrete model/invoke identity。
- 仍待后续合同：MS5-IDENTITY immutable credential/connection revisions and restart identity；Phase 4 Merge Gate / P4 Manual Production Alpha。
