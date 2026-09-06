# Task: MS4-LITE-MODE-SEMANTICS

## Read first

- [`../README.md`](../README.md)
- `04-DRAMAFORGE_MODEL_SUPPLY_DESIGN.md` §§4–7;
- `05-DRAMAFORGE_MODEL_SUPPLY_IMPLEMENTATION_PLAN.md` §7 (MS4-01 through MS4 Gate);
- `06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md` §12;
- `07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md` §10;
- current `manifest.py`, `validator.py`, `intent_bridge.py`, V3 contracts, selection and snapshot tests.

## Current Evidence

- MS2 (`a1f8a1e`) supplies canonical roles and strict slot/cardinality validation; MS3 (`44558de`) preserves ordered `ResolvedReference` lists through the bridge.
- `CapabilitySpec` currently exposes only flattened `input_slots`, options and constraints. `ExclusiveGroup` is converted into flattened `mutually_exclusive` data, which cannot represent first+last together inside one mode while excluding omni-reference inputs.
- V3 request contracts have no input `mode_id`; `CapabilityRouter` validates only the flattened capability spec, while Professional `SelectionPlan` keeps the model-selection mode string rather than a distinct input-mode identity.
- `ExecutionModelResolution.mode_id` already exists and is snapshotted, but its value is currently populated from the selection mode instead of a stable input-mode contract.

## Target

Implement the bounded MS4-LITE slice:

1. Add typed `InputModeSpec` and additive `CapabilitySpec.modes` / `default_mode` fields while preserving legacy fields and behavior when `modes` is empty.
2. Add optional `mode_id` to V3 image/video request contracts and carry it through the intent bridge.
3. Add `CapabilityValidator.validate_mode()` to validate selected mode existence, mode-level slot/cardinality/options/constraints; unknown or missing mode must fail closed when a capability declares modes.
4. Convert A+B `ExclusiveGroup` mode-like members into explicit V3 modes instead of flattening them into mutually-exclusive slot guesses; do not invent modes for unverified seed capabilities.
5. Make the Professional selection plan/resolution snapshot carry a distinct stable input `mode_id` (text, first-frame, first-last-frame, omni-reference as derivable defaults) without merging existing video capability enum vocabulary.
6. Keep mode selection and validation before adapter/provider dispatch; no real Provider calls.

## Allowed

- `backend/app/providers/manifest.py`, `validator.py`, `intent_bridge.py`, `intents.py`, `router.py`, `selection.py` and narrow V3 request contract files;
- focused mode/manifest/selection/snapshot tests and this Task Contract.

## Forbidden

- no `VIDEO_GENERATE` capability merge or large Registry/provider-contract migration;
- no MS5 credential/connection/runtime identity changes;
- no MS3 ordered-reference redesign or role deduplication;
- no Provider calls, automatic fallback, silent mode inference after an explicitly supplied mode, or Provider-name branching;
- do not alter unverified catalog seed capability declarations merely because the schema can express future modes.

## Acceptance

- mode schema and legacy compatibility are covered;
- text, first-frame, first+last, omni-reference and illegal mixed-mode validation are covered;
- unknown/missing mode and required-slot/cardinality/options failures occur before adapter `create`;
- an A+B exclusive group becomes explicit mode records with mode-level slots, not flattened slot exclusivity;
- `mode_id` is carried in bridge intent, `SelectionPlan`, `ExecutionModelResolution`, NodeRun snapshot and ProviderOperation selection/request evidence where those paths already persist the result;
- existing MS1/MS2/MS3, compiler, identity and full unit regressions pass.

## Tests

- focused `tests/unit/test_v3_router.py`, `test_intent_normalizer.py`, `test_model_selection.py`, `test_execution_model_resolution.py` and `test_unified_path.py` mode tests;
- existing adapter/compiler/registry regressions;
- `ruff`, `mypy`, backend unit suite and active-plan/reference compliance checks.

## Drift

This Task adds explicit mode contracts and snapshot identity only. Concrete runtime/provider connection revisions remain MS5-R / MS5-IDENTITY; broader capability vocabulary convergence and Workbench UI merge remain later phases.


## Implementation Result (2026-08-26)

- **Status：COMPLETED**。
- `manifest.py` 新增 typed `InputModeSpec`，`CapabilitySpec` 增加 additive `modes` / `default_mode`，并保留无 modes 时的 legacy contract；A+B mode-like `ExclusiveGroup` 会转换为显式 `first_frame`、`first_last_frame` 或 `omni_reference` mode，不再 flatten 为 slot 互斥猜测。
- V3 image/video request contracts 新增可选 `mode_id`；intent bridge 将其带入 A+B intent。`CapabilityRouter` 现在在 adapter `create()` 前调用 `validate_mode()`。
- `CapabilityValidator.validate_mode()` 对 declared modes 执行 mode 存在性、required/min/max slot、option 和 constraint 校验；未声明或缺失 mode 以稳定 `UNSUPPORTED_MODE` fail-closed，跨 mode 输入以 `UNSUPPORTED_INPUT_SLOT` fail-closed。
- `SelectionPlan` 新增独立的 input `mode_id`；Professional selection 根据显式 mode 或输入形状保存 `text_to_video`、`first_frame`、`first_last_frame`、`omni_reference`、`text_to_image` / `reference_image`，并由既有 `ExecutionModelResolution`、NodeRun snapshot、ProviderOperation selection/request evidence 继续冻结。
- 未合并 capability vocabulary、未大规模迁移 Registry/provider contracts、未触碰 MS5 runtime identity/credential revision，也未进行真实 Provider 调用。

## Acceptance Evidence

- MS4 focused mode/manifest/router tests：`backend/tests/unit/test_v3_router.py`，31 passed。
- Bridge/compiler/identity regressions：`backend/tests/unit/test_v3_adapters_v2.py`、`backend/tests/unit/test_v3_identity.py`、`backend/tests/unit/test_compilers.py`，39 passed。
- Model selection / NodeRun snapshot mode identity：`backend/tests/unit/test_model_selection.py`、`backend/tests/unit/test_unified_path.py`，29 passed。
- Backend unit suite：699 passed，1 warning。
- Static checks：`ruff check app tests alembic/versions` passed；`mypy app` passed；active seven-plan reference verifier and directory compliance passed；`git diff --check` passed。
- No migration, Provider call or paid execution was introduced.

## Drift Closed / Deferred

- 已关闭：flattened capability-only input contract；mode selection/validation 缺少稳定 identity；mode-specific required slot/cardinality/options 未在 dispatch 前统一验证；A+B mode-like exclusivity 被错误表达为普通互斥。
- 仍待后续合同：MS5-R concrete runtime resolution、MS5-IDENTITY immutable credential/connection revisions、Phase 4 Merge Gate 与 Workbench UI 的完整 mode state。
