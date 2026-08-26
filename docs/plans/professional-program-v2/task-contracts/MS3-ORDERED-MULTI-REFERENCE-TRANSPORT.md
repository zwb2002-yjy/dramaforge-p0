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
