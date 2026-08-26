# Task: Phase 10 — UI 收口（P10-01 / P10-02）

## Status

- **State:** IN PROGRESS
- **Task id:** `p10-ui-consolidation`
- **Program order:** Phase 9（COMPLETED）→ **Phase 10 UI 收口（本任务）** → P10-03..07 审计 / Golden / E2E / V1 Gate
- **Task boundary:** P10-01 `/quick` Legacy UI 降级（不删除、不默认入口、加 Legacy 说明、不再开发新功能）；P10-02 `projects.$projectId.production.tsx` 收口为「跨场景 Production Monitor」（移除 Script Import / 预算证据主面板 / 旧大 Storyboard 主工作区，这些能力已迁到新 Scene Workbench）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §88-89
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) 工作台心智

## Owned paths

- `frontend/src/routes/projects.$projectId.quick.tsx`
- `frontend/src/routes/projects.$projectId.production.tsx`
- `frontend/src/features/production/ProductionMonitor.tsx`
- `frontend/tests/unit/ProductionMonitor.test.tsx`
- `frontend/tests/e2e/director_workflow.spec.ts`
- `docs/plans/professional-program-v2/task-contracts/P10-UI-CONSOLIDATION.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- `/quick` 不再 redirect：显示 Legacy 说明（不删、不默认入口、说明已由专业工作台替代）；e2e 断言更新。
- `/production` 为跨场景 Production Monitor：场景汇总卡（scenes/shots/formal keyframe/video/risk/node run 完成/失败/artifacts）+ 场景列表（点击进 Scene Workbench）；移除 script-import-panel / ① 导入剧本 / 旧 studio 分镜板+shot-detail+snapshot+ArtifactStage 主工作区；保留 ProfessionalWorkbench 与导出（② 导出 / ③ 授权下载）。
- 移除后无未使用 import；`tsc/build/eslint` 通过；vitest 全量通过；e2e director_workflow 更新后通过；后端无改动。
