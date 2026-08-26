# Task: Phase 10 — Migration / No-Guess Backfill Audit（P10-03 / P10-04）

## Status

- **State:** IN PROGRESS
- **Task id:** `p10-migration-noguess-audit`
- **Program order:** Phase 10 UI 收口（COMPLETED）→ **本任务（P10-03/04 审计）** → P10-05 RLS + 07 §23 Model Resolution Audit → Golden / E2E / V1 Gate
- **Task boundary:** P10-03 Historical Project Migration Audit（旧 Project 的 script/scene/shot/character/canonical/node run/provider operation/artifact/export 均可被新 Workbench 读取）；P10-04 No Guess Backfill Audit（无自动猜 Formal Keyframe/Video；NULL 可存在；UI 显示「尚未选择正式结果」）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §90-91
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) 数据模型（script/scene/shot/character/canonical/node run/provider operation/artifact/export）

## Owned paths

- `backend/tests/integration/test_phase10_migration_audit_pg.py`
- `backend/tests/integration/test_catalog_migration_pg.py`（stale `upgrade head` 断言更新为当前 head 20260827_0049）
- `frontend/src/features/workbench/CinematicCanvas.tsx`
- `frontend/tests/unit/SceneWorkspace.test.tsx`
- `docs/plans/professional-program-v2/task-contracts/P10-MIGRATION-NOGUESS-AUDIT.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- 真实 PG 集成测试：用旧路径 `import_script` 种入历史 Project（script/episode/scene/shot）+ Character/CharacterReference(canonical) + ProductionGraph/NodeRun/ProviderOperation/Artifact + Export/ExportItem；通过新 Scene Workbench 服务（SceneSummaryService / SceneWorkspaceService / ShotWorkbenchService / build_execution_trace / script 与 export 读取）断言全部可读。
- P10-04：无 formal 结果的 Shot 在 Workbench 读取后 formal_keyframe/video 仍为 NULL（无 backfill）；`require_formal_keyframe` 以 NO_FORMAL_KEYFRAME 失败关闭。
- 前端：`CinematicCanvas` 在无 formal keyframe/video 时显示「尚未选择正式结果」；`SceneWorkspace.test.tsx` 断言更新。
- 全量 unit / integration（TEST_PG_ENABLED=1）通过；ruff/mypy 通过。
