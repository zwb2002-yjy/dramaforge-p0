# Task: MS3-ORDERED-MULTI-REFERENCE-TRANSPORT

## Read first

- [`../README.md`](../README.md)
- `04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md` §3.4;
- `05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md` §6 (MS3-01 through MS3 Gate);
- `06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` §11.3;
- `07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` §§15–16;
- current `adapter.py`, `adapters_v2.py`, provider compiler boundaries and `test_v3_adapters_v2.py`.

## Current Evidence

- MS2 (`a1f8a1e`) established canonical singular roles and strict cardinality validation.
- `app.providers.runtime.ResolvedReference` is already an ordered list item, but `ModelAdapter.translate`, `LegacyAdapterBridge._compile` and `LegacyAdapterBridge.create` still expose or rebuild `dict[str, ResolvedArtifact]`.
- `LegacyAdapterBridge.create()` first builds a dict from request role pairs and then reconstructs another dict from resolver output; repeated `reference_image` values overwrite earlier artifacts before the compiler sees them.
- The A+B provider compilers already consume `list[Any]` references for video; the bounded fix is to preserve the list through the bridge and add a compatibility adapter for old mapping callers. Image intent remains single-reference in this task; if a future manifest permits multiple image refs, the bridge must fail explicitly rather than select index zero.

## Target

Implement the smallest MS3 ordered-reference transport slice:

1. Make the bridge's new internal and `translate_v2` path use `list[ResolvedReference]` end-to-end.
2. Keep the existing `translate` mapping input as a narrow compatibility surface, converting it to an ordered list without claiming that a pre-collapsed mapping can restore duplicates.
3. Remove bridge-side role→single-artifact reconstruction from `create`; resolver output must pass as an ordered list to the compiler.
4. Preserve order, repeated canonical roles, artifact IDs, MIME types, URLs/bytes and fingerprints from request resolver to compiler.
5. For the legacy image-intent single-reference limitation, reject multiple image references explicitly with `UNSUPPORTED_BY_LEGACY_BRIDGE`; never silently take `reference_images[0]` when the list has more than one item.

## Allowed

- `backend/app/providers/adapter.py`, `adapters_v2.py`, narrow provider compiler compatibility helpers needed to consume ordered references;
- focused adapter/identity/compiler tests and the MS3 Task Contract.

## Forbidden

- no MS4-LITE mode/exclusivity redesign;
- no P4 `PlannedReference` or new execution planning ORM;
- no credential/connection/runtime identity changes;
- no role-based deduplication, set conversion, automatic fallback or Provider calls;
- do not rewrite unrelated Legacy Provider APIs.

## Acceptance

- 1 reference, 3 same-role references, mixed image+video references and order/fingerprint preservation are covered;
- a compiler receives all 3 same-role references in their original order;
- resolver output is not converted through a role-keyed dict;
- old mapping callers remain compatible for unique roles;
- image bridge rejects >1 image reference with stable `UNSUPPORTED_BY_LEGACY_BRIDGE` instead of silently selecting the first;
- existing adapter, compiler, identity, resolver, selection and full unit regressions pass.

## Tests

- focused `tests/unit/test_v3_adapters_v2.py` MS3 tests;
- existing adapter/compiler/identity tests;
- `ruff`, `mypy`, backend unit suite and active-plan/reference compliance checks.

## Drift

This Task closes bridge-level ordered multi-reference loss only. The broader P4 plan/reference distinction, mode identity and credential/connection immutable revisions remain later tasks.


## Implementation Result (2026-08-26)

- **Status：COMPLETED**。
- `LegacyAdapterBridge` 现在以 `list[ResolvedReference]` 作为新的 `translate_v2` / 内部编译输入；`create` 不再把请求或 resolver 输出重建为 `dict[role, artifact]`，因此同 role 多参考会原样传入 Compiler。
- 旧 `translate` mapping 调用保留为窄兼容层：只将已有 mapping 按插入顺序转换为 list；它不会声称能恢复调用方已经丢失的重复 role。
- 新增 `OrderedReferenceAdapter` 可选协议，明确 MS3 的 list-based translation surface；现有旧 ModelAdapter、LiteLLM 和 bootstrap 适配器不被强制同时迁移。
- Image Intent Bridge 对超过一张 reference image 返回稳定 `UNSUPPORTED_BY_LEGACY_BRIDGE`，不再静默取 `reference_images[0]`； Agnes/Ark image compiler 也移除 role-keyed reconstruction，并对多图显式拒绝。

## Acceptance Evidence

- Ordered bridge tests：`backend/tests/unit/test_v3_adapters_v2.py`，20 passed；覆盖 1 reference、3 个同 role reference、混合 image/video role、order/fingerprint preservation、resolver output 直达 Compiler、legacy image multi-reference rejection。
- Existing compiler and identity regressions：`backend/tests/unit/test_compilers.py` + `backend/tests/unit/test_v3_identity.py`，19 passed。
- Backend unit suite：693 passed，1 warning。
- Static checks：`ruff check app tests alembic/versions` passed；`mypy app` passed；`git diff --check` passed；active seven-plan reference verifier and directory compliance passed。
- No migration, Provider credential/runtime identity change or real Provider call was introduced.

## Drift Closed / Deferred

- 已关闭：Bridge `dict[role, artifact]` 覆盖同 role 多参考；resolver output 到 Compiler 的顺序/指纹丢失；Legacy image bridge 静默只取第一张。
- 仍待后续合同：MS4-LITE mode identity/exclusivity；MS5-R / MS5-IDENTITY execution identity and immutable revisions；P4 `PlannedReference` 与 Workbench execution merge。
