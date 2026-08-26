# Task: MS2-STRICT-REFERENCE-SLOT-VALIDATION

## Read first

- [`../README.md`](../README.md)
- `06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` §11;
- `07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` §6 and the MS2 references in `05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md`;
- `04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md` §§3.2–3.3 and the current `manifest.py`, `validator.py`, `normalizer.py`, `intent_bridge.py`, V3 contracts and focused tests.

## Current Evidence

- MS1-R/MS1-C is completed at `edd67db`; Professional execution now has one concrete model-resolution result and fails closed before Provider submission when the selected model is unavailable.
- The canonical role vocabulary already exists in the A+B manifest bridge (`first_frame`, `last_frame`, `reference_image`, `reference_video`, `reference_audio`), but V3 `ReferenceToVideoRequest` is still counted under plural field names (`reference_images`, `reference_videos`, `reference_audio`).
- `CapabilityValidator._validate_input_slots()` currently continues when a request role is absent from the manifest, which violates the reviewed `UNSUPPORTED_INPUT_SLOT` fail-closed rule.
- Cardinality checks exist for declared roles, but the plural/canonical mismatch prevents them from applying consistently; media-type checks are not enforced against resolved artifact MIME metadata.

## Target

Implement the smallest MS2 strict-validation slice:

1. Define and use one canonical reference-role vocabulary for all internal manifest/validator/normalizer/bridge paths.
2. Convert plural request containers to canonical roles without changing the public request field names.
3. Make every request role absent from a capability manifest fail closed with stable `UNSUPPORTED_INPUT_SLOT` details before compiler/Provider dispatch.
4. Enforce declared slot media types against resolved artifact MIME metadata when that metadata is supplied at the validation boundary.
5. Enforce required/minimum/maximum cardinality for first/last frame and multi-reference containers, preserving request order and allowing repeated references for later MS3 transport work.

## Allowed

- `backend/app/providers/reference_roles.py`;
- `backend/app/providers/manifest.py`, `validator.py`, `normalizer.py`, `intent_bridge.py`, V3 contracts/router boundary and focused tests;
- narrow compatibility adapters needed to keep existing provider/compiler behavior while canonical roles are used internally.

## Forbidden

- no Provider calls, credentials, catalog, connection or runtime identity changes;
- no MS3 `list[ResolvedReference]` transport rewrite beyond retaining repeated canonical counts at validation input;
- no MS4 mode/exclusivity redesign beyond preserving existing manifest constraint validation;
- no silent dropping, role deduplication, automatic fallback or Provider-name branching;
- do not weaken existing strict-validation or legacy compatibility tests.

## Acceptance

- canonical role tests cover all five roles and plural request-field normalization;
- an undeclared request role raises `UNSUPPORTED_INPUT_SLOT` with the role in details;
- required slot missing, maximum exceeded and valid below-maximum cardinality are covered;
- resolved image/video/audio artifacts are rejected when their MIME type does not match the manifest slot; absent resolved metadata remains a valid pre-resolution validation mode;
- invalid requests fail before adapter `create` is called;
- current resolver, selection, compiler and router regressions pass.

## Tests

- focused MS2 role/validator tests;
- existing `tests/unit/test_v3_router.py`, `test_intent_normalizer.py`, eligibility and compiler tests;
- `ruff`, `mypy`, backend unit suite and active-plan/reference compliance checks.

## Drift

This Task closes only canonical role identity, strict unknown-slot rejection, media-type validation at the resolved-artifact boundary and cardinality enforcement. Ordered multi-reference delivery remains MS3; mode identity and exclusivity remain MS4-LITE.
