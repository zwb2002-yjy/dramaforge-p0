# Task: P3 — Phase 3 场景中心专业工作台（Scene Wall / Scene Workspace / Shot Workbench / Canvas / Asset bindings）

## Status

- **State:** COMPLETE
- **Program order:** Professional P0 → Phase 1 (P1) → Phase 2 (P2) → **Phase 3 (P3)** → MS0 → MS1-R → MS1-C → MS2 → MS3 → MS4-LITE → MS5-R → MS5-IDENTITY-A/B/C → Phase 4 Merge Gate → P4
- **Task boundary:** 完成 07 §4 Phase 3：Scene Wall、Scene Workspace、Shot Workbench、Canvas、Asset bindings；仍不把 Provider 生成作为主要目标。Phase 3 是 Phase 4 Merge Gate 前置。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §4 Phase 3、§15 Merge Gate
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §22–§29（P3-01..P3-06 与 Phase 3 Gate）
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) §40 路由、§43 Scene Storyboard Wall、§6/§7 Scene/Shot 字段、§14 ShotReferenceBinding
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) §14 项目总览=故事板墙、§20 点击镜头后的状态驱动
- Completed `P2-PHASE2-ASSET-REFERENCES.md`（AssetVersion/Reference/Tag/Binding 已在 P2 落库）

## Current evidence / drift

- `Scene.design_state`、`Shot.director_state/image_prompt/video_prompt/formal_*_artifact_id` 已在 P1 落库；`ShotReferenceBinding` 与 `@Asset` 解析已在 P2 落库。
- 尚无 Scene Summary / Scene Workspace / Shot Workbench 聚合 API；`GET /projects/{id}/scenes` 未实现。
- 前端 `/scenes` 目前是占位页；无 SceneStoryboardWall / SceneWorkspace / ShotStrip / ShotDesignPanel；ProductionPage 存在按 `input_snapshot.shot_id` 过滤 runtime JSON 的旧模式，P3 需改为后端聚合。

## Implementation summary（子任务）

1. **P3-01 Scene Summary API**：`GET /projects/{project_id}/scenes` 返回 `SceneSummary`（id/scene_number/location_name/time_of_day/synopsis/version/shot_count/formal_keyframe_count/formal_video_count/risk_count/representative_artifact）；批量聚合（单批 SQL，禁止 per-scene N+1 NodeRun 查询）。
2. **P3-02 Scene Storyboard Wall**：`frontend/src/features/workbench/SceneStoryboardWall.tsx`；卡片=代表图/场景名/时间/shot count/状态；操作=进入/拖拽排序/复制（调用 P3-03）。
3. **P3-03 Scene Structural Commands**：`SceneService`：reorder、copy、split preview、split、merge preview、merge；split/merge 必须先 preview（返回 affected shots/experiments/formal media）再执行。
4. **P3-04 Scene Workspace Snapshot**：`GET /projects/{project_id}/scenes/{scene_id}/workspace`，只返回当前 Scene 所需数据（scene、shots、director state、prompts、references、formal artifacts、trace summary）。
5. **P3-05 Scene Workspace UI**：`SceneWorkspace.tsx` / `CinematicCanvas.tsx` / `ShotStrip.tsx` / `ShotProductionTrace.tsx` / `ShotDesignPanel.tsx`；布局=左/下镜头序列、中大画布、右导演面板占位、底生产链轨迹；中央区域按状态显示 导演构图预览 / 关键帧 / 视频 Player。
6. **P3-06 Shot Workbench Snapshot**：`GET /projects/{project_id}/shots/{shot_id}/workbench` 后端聚合（Shot、Scene、Prompt、Director State、References、Formal Artifact、Candidates、Production Trace summary、Asset old-version warnings）；停止新 UI 自行解析 runtime JSON。
7. **P3-07 Canvas / Asset bindings 收口**：SceneWorkspace 内可修改画面描述（复用 canvas PATCH 乐观锁）、image/video prompt（复用 Shot Design PATCH）、选择 Asset Reference（复用 P2 binding/picker）；`/scenes/$sceneId` 路由接入。

## Owned paths

- `backend/app/assets/scene_service.py`
- `backend/app/workbench/scene_service.py`
- `backend/app/api/v1/scenes.py`
- `backend/app/api/v1/workbench.py`
- `backend/app/api/v1/router.py`
- `backend/tests/unit/test_scene_summary_api.py`
- `backend/tests/unit/test_scene_workspace_snapshot.py`
- `backend/tests/unit/test_shot_workbench_snapshot.py`
- `backend/tests/unit/test_scene_structural_commands.py`
- `frontend/src/features/workbench/**`
- `frontend/src/routes/projects.$projectId.scenes.tsx`
- `frontend/src/routes/projects.$projectId.scenes.$sceneId.tsx`
- `frontend/src/routes/projects.$projectId.tsx`（根路由 last-view 恢复目标 /scenes）
- `frontend/tests/unit/SceneStoryboardWall.test.tsx`（随实现提交）
- `frontend/tests/unit/SceneWorkspace.test.tsx`（随实现提交）
- `docs/plans/professional-program-v2/task-contracts/P3-PHASE3-SCENE-WORKBENCH.md`
- `docs/开发执行检查点.md`

> 台账说明：`test_shot_workbench_snapshot.py` 的 shot workbench 用例合并在 `test_scene_workspace_snapshot.py`（同属 snapshot 聚合验证）；`frontend/tests/unit/SceneStoryboardWall.test.tsx`、`SceneWorkspace.test.tsx` 与 `routeTree.gen.ts` 随实现提交登记（非台账 HEAD 证据提交）。

## Explicitly out of scope

- Provider 生成 / 真实模型调用；P4 WorkbenchExecutionPlan 执行期消费。
- Director Agent / 自动 Proposal；3D 完整实现（保留粗 3D 导演台占位）。
- 语义搜索 / embedding / 自动推荐。
- 额外总规划或并行改写共享 Schema。

## 完成证据（实现摘要）

- **P3-01**：`GET /projects/{id}/scenes` 返回 `SceneSummary`（shot_count/formal_keyframe_count/formal_video_count/risk_count/representative_artifact），单批聚合（一次 scene 查询 + 一次按 scene 分组的 shot 统计 + 一次 representative artifact 查询），无 per-scene N+1。
- **P3-02**：`SceneStoryboardWall.tsx`（卡片=代表图/场景名/时间/shot count/状态；进入/拖拽排序/复制）。
- **P3-03**：`assets/scene_service.py` 的 `SceneStructureService`：reorder/copy/split-preview/split/merge-preview/merge；split/merge 必须先 preview（affected shots/experiments/formal media）。
- **P3-04**：`GET /projects/{id}/scenes/{scene_id}/workspace` 仅返回该场景数据（scene+shots+bindings+candidates+trace）。
- **P3-05**：`SceneWorkspace.tsx` / `CinematicCanvas.tsx` / `ShotStrip.tsx` / `ShotProductionTrace.tsx` / `ShotDesignPanel.tsx`；布局=镜头序列/大画布/右侧导演面板/底部生产链轨迹；中央区域按 无→有→关键帧→视频 显示 占位/关键帧/播放器。
- **P3-06**：`GET /projects/{id}/shots/{shot_id}/workbench` 后端聚合（Shot/Scene/Prompt/Director State/References/Formal Artifacts/Candidates/Trace/old-version warnings）；新 UI 不解析 runtime JSON。
- **P3-07**：`/scenes/$sceneId` 路由接入；ShotDesignPanel 复用 P1 Shot Design PATCH（409 乐观锁），AssetReferencePicker 复用 P2 binding；根路由 last-view 恢复目标 `/scenes`。
- 附带加固：`AssetReferencePicker` 对非数组 API 响应做防御（Array.isArray guard），避免 `{}.map` 崩溃。

## Verification gate（全部通过）

- Scene Summary 批量聚合正确（shot/formal/risk 计数、representative_artifact）、无 N+1（单批查询实现）。
- Scene Workspace / Shot Workbench snapshot 仅返回 scene/shot 范围数据，不返回全项目 NodeRun 历史。
- Split/Merge preview 先返回 affected shots/experiments/formal media，确认后才执行。
- Shot Design（prompt/director_state）与 Asset Reference 编辑复用 P1/P2 端点，乐观锁仍 409。
- 后端全量 unit：`746 passed / 1 warning`（+8 个 P3 测试）；`ruff`、`mypy`(196)、`compileall`、directory compliance、`git diff --check` 通过；无新迁移（迁移链 head 仍为 `20260826_0044`）。
- 前端：`tsc --noEmit`、`vite build` 通过；vitest `72 passed`（+4 个 P3 组件测试）；eslint 0 errors（仅既有 CreativeStage Fast Refresh warning）；Playwright `8 passed`。Phase 3 Gate 流程可走通（场景墙→场景→Shot→改画面描述→改 prompt→选引用→保存→切换→重开继续）。
- PostgreSQL 集成仅在可达时执行，否则如实 skip；零真实 Provider 调用。
