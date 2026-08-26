# Task: P4-03/MS8 Dynamic Model Controls（Manifest 驱动模型控件）

## Status

- **State:** IN PROGRESS
- **Task id:** `p4-03-manifest-model-controls`
- **Program order:** P4-02（COMPLETED）→ **P4-03/MS8 Dynamic Model Controls（本任务）** → P4-04 → …
- **Task boundary:** 只做前端 Manifest 驱动控件（ModelPicker / DynamicCapabilityForm / AdvancedModelOptions / ReferencePurposeEditor）；不接执行 API。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §16 P4-03
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §33 Task P4-03
- 现有 `frontend/src/lib/manifestOptions.ts`（`uiComponentFor` / `allowedValuesFor`）

## 依据（03 §33 / 07 P4-03）

- 新增 `frontend/src/features/model-controls/`：`ModelPicker`、`DynamicCapabilityForm`、`AdvancedModelOptions`、`ReferencePurposeEditor`。
- 数据直接使用现有 `GET /models`、`GET /models/{model_id}`（`listModels` / `getModelManifest`）。
- 禁止：`if (model === "seedance") ...`、`if (provider === "agnes") ...`；前端只消费 ModelManifest / Eligibility / Quality evidence / Execution preview。
- Test：给模拟 Manifest（enum、slider、boolean、conditional、mutually exclusive），UI 必须正确变化。

## Owned paths

- `frontend/src/features/model-controls/ModelPicker.tsx`
- `frontend/src/features/model-controls/DynamicCapabilityForm.tsx`
- `frontend/src/features/model-controls/AdvancedModelOptions.tsx`
- `frontend/src/features/model-controls/ReferencePurposeEditor.tsx`
- `frontend/src/features/model-controls/index.ts`
- `frontend/tests/unit/ModelControls.test.tsx`
- `docs/plans/professional-program-v2/task-contracts/P4-03-MANIFEST-MODEL-CONTROLS.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-05 WorkbenchExecutionService / API / 真实模型执行。
- 修改 07/03 方案正文。

## Verification gate（本任务完成标准）

- 组件无任何 provider/model 名分支；所有控件形状来自 `CapabilitySpecRead`。
- enum→select、slider(min/max)→slider、boolean→switch、conditional 联动、mutually exclusive 禁用逻辑正确。
- vitest `ModelControls.test.tsx` 通过；`tsc --noEmit`、`vite build`、eslint 通过。
