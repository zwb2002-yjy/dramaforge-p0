# Task: P4-04 Model Profile 简化 + voice_model_id（Phase 4 Manual Production Alpha）

## Status

- **State:** COMPLETE
- **Task id:** `p4-04-model-profile-simplification`
- **Program order:** P4-03（COMPLETED）→ **P4-04 Model Profile 简化（本任务）** → P4-05 → …
- **Task boundary:** 只在既有 Simple Mode 上补 `voice`（audio.tts slot）并统一"默认X模型"文案；不改后端 slot 语义。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §34 Task P4-04
- 现有 `frontend/src/lib/modelProfile.ts`、`frontend/src/components/provider/ModelProfileSettings.tsx`

## 依据（03 §34）

- 现有 `SimpleModeSelection` 补 `voice_model_id`（映射 `audio.tts` slot）。
- Professional 项目设置只显示：默认语言模型、默认图片模型、默认视频模型、默认声音模型。
- 底层仍映射当前 Model Slot（`bindings` 单一 truth，Simple Mode 只生成 patch）。

## Owned paths

- `frontend/src/lib/modelProfile.ts`
- `frontend/src/components/provider/ModelProfileSettings.tsx`
- `frontend/tests/unit/modelProfile.test.ts`
- `docs/plans/professional-program-v2/task-contracts/P4-04-MODEL-PROFILE-SIMPLIFICATION.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- 后端 ModelSlot 语义变更。
- P4-05 执行服务 / API / 真实模型执行。
- 修改 03/07 方案正文。

## Verification gate（本任务完成标准）

- `SIMPLE_MODE_SLOT_GROUPS` 含 `voice: ["audio.tts"]`；`SimpleModeSelection` 含 `voice?`。
- Simple UI 显示四组：默认语言 / 图片 / 视频 / 声音模型。
- `simpleModeToBindings` 对 voice 生成 `audio.tts` patch。
- vitest `modelProfile.test.ts` 更新并通过；全量 vitest、tsc、build、eslint 通过。
