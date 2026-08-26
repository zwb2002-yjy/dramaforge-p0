# Task: P1 — Professional Workspace Foundation

## Status

- **State:** COMPLETE
- **Program order:** Professional P0 → Phase 1 → Phase 2 → Phase 3 → MS0 → MS1-R → MS1-C → MS2 → MS3 → MS4-LITE → MS5-R → MS5-IDENTITY-A/B/C → **Phase 4 Merge Gate** → P4
- **Task boundary:** Add the minimal professional workspace data model and project-shell navigation. Do not implement generation, scene wall, asset cards, director agent, or 3D. Phase 1 is a Phase 4 Merge Gate prerequisite (07 plan §4/§15).

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §4 Phase 1、§15 Merge Gate
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) §6.1 SceneDesignState、§7.1 ShotDirectorState、§40 前端路由、§41 ProjectWorkspaceShell 重构、§61 Workspace State API
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) §14 项目总览 = 故事板墙（场景总览为项目首页方向）
- Completed `MS5-IDENTITY-C-EXECUTION-IDENTITY-FREEZE.md`

## Current evidence / drift

- `UserProjectPreference` 已含 `workspace_state`，`Scene.design_state`、`Shot.director_state/image_prompt/video_prompt/formal_*_artifact_id`、`Asset.current_version_id` 已在 ORM 声明；迁移 `20260826_0043` 覆盖全部新列并保持单 head。
- 尚无 workspace-state API、shot design API、workbench 服务目录或专业 shell 路由，均在本合同补齐。
- `Shot.version` 已存在；Shot Design PATCH 使用 `expected_version` 乐观并发（409），与 CanvasRevision/Asset PATCH 同一模式。

## Implementation summary

1. **P1-01 Workspace State**
   - `backend/app/workbench/workspace_state_service.py`：`get_workspace_state` / `update_workspace_state`（按 (user, project) 读取或创建 preference，PATCH 为 merge 语义）。
   - `backend/app/api/v1/workbench.py`：`GET/PATCH /projects/{project_id}/workspace-state`。
   - `frontend/src/hooks/useProjectWorkspaceState.ts`：query + mutation，`rememberLastView` / `rememberState`，`workspaceViewFromPath` 解析专业视图。
   - 路由恢复：项目根 `/projects/{projectId}` 在存在有效 `last_view` 且无显式 anchor 时重定向到上次视图；项目总览保留 `模型设置`（`#model-settings` anchor 不重定向），并展示“继续上次查看”入口。
   - 测试：`backend/tests/unit/test_workspace_state.py`（默认空、round-trip、merge、跨用户 404）。

2. **P1-02 Scene / Shot Professional Fields**
   - 迁移 `20260826_0043_professional_workspace_foundation.py`（upgrade/downgrade 完整，FK RESTRICT + 索引）。
   - `backend/app/assets/schemas.py`：`SceneDesignState` 与 `ShotDirectorState`（结构化 framing/camera/action/gaze/composition/continuity/model_overrides/video_reference_risk）。
   - 测试：`test_scene_design_state.py`、`test_shot_director_state.py`（默认值 + 设计示例 round-trip）。

3. **P1-03 Shot Design API**
   - `backend/app/workbench/shot_service.py`：`update_shot_design` 校验项目归属 → `with_for_update` 读 Shot → 版本比对 → 写 director_state/image_prompt/video_prompt → `version += 1`；不生成媒体、不要求 Director Agent 批准。
   - `backend/app/api/v1/workbench.py`：`PATCH /projects/{project_id}/shots/{shot_id}/design`（body 含 `expected_version`；director_state 经 `ShotDirectorState` 校验后落库）。
   - 测试：`test_shot_design_concurrency.py`（写导演状态+prompts、stale version 409、跨用户 404）。

4. **P1-04 Professional Project Shell**
   - `frontend/src/features/creation-preview/ProjectWorkspaceShell.tsx`：在原文上演进，导航改为 剧本/资产/场景/专业生产/剪辑（+项目大厅、模型设置），移除 StageStepper；保留 evidence inspector。
   - 新路由：`projects.$projectId.script/assets/scenes/edit.tsx`（Phase 1 占位页，标注随阶段落地）；`routeTree.gen.ts` 注册。
   - `/quick` 保持 legacy 并继续重定向专业生产。
   - `frontend/src/lib/api.ts`：`fetchWorkspaceState` / `updateWorkspaceState` / `updateShotDesign`。

## Owned paths

- `backend/app/access/models.py`
- `backend/app/assets/models.py`
- `backend/app/assets/schemas.py`
- `backend/alembic/versions/20260826_0043_professional_workspace_foundation.py`
- `backend/app/workbench/**`
- `backend/app/api/v1/workbench.py`
- `backend/app/api/v1/projects.py` (登记 workbench.router)
- `backend/tests/unit/test_workspace_state.py`
- `backend/tests/unit/test_scene_design_state.py`
- `backend/tests/unit/test_shot_director_state.py`
- `backend/tests/unit/test_shot_design_concurrency.py`
- `frontend/src/hooks/useProjectWorkspaceState.ts`
- `frontend/src/features/creation-preview/ProjectWorkspaceShell.tsx`
- `frontend/src/routes/projects.$projectId.tsx`
- `frontend/src/routes/projects.$projectId.script.tsx`
- `frontend/src/routes/projects.$projectId.assets.tsx`
- `frontend/src/routes/projects.$projectId.scenes.tsx`
- `frontend/src/routes/projects.$projectId.edit.tsx`
- `frontend/src/routeTree.gen.ts`
- `docs/plans/professional-program-v2/task-contracts/P1-PROFESSIONAL-WORKSPACE-FOUNDATION.md`
- `docs/开发执行检查点.md`

> 说明：P1 STARTED 台账 `owned_paths` 使用 `frontend/src/routes` 目录前缀；路由注册表 `frontend/src/routeTree.gen.ts`
> 随实现提交（非台账 HEAD 证据提交）一并登记新路由，属路由目录的功能延伸。台账 HEAD 证据提交只含本合同与检查点。

## Explicitly out of scope

- 场景墙 / 场景工作区 / 镜头工作台 / 画布（Phase 3）。
- 资产卡 / AssetTag / ShotReferenceBinding / @Asset 解析（Phase 2）。
- 生成、导演智能体、3D、真实 Provider 调用。
- 额外总规划或并行改写共享 Schema。

## Verification gate

- 新 shell 路由 `/script` `/assets` `/scenes` `/edit` 渲染无错误；`/production` 与 `/quick` 不变；全部 8 个 Playwright e2e 通过。
- Workspace state 持久化并恢复 last view：backend 测试证明 GET/PATCH/merge/跨用户隔离；前端根路由在存在 last_view 时恢复。
- 迁移 `20260826_0043` 单 head、offline `alembic upgrade head --sql` 通过；ORM/迁移字段一致。
- Shot design 409：`test_shot_design_concurrency.py` 验证 stale version 返回 `CONFLICT`/409。
- 后端全量 unit：`727 passed / 1 warning`（含 10 个新增 P1 测试）；`ruff check app tests alembic/versions` 通过；`mypy app` Success（189 source files）。
- 前端：`tsc --noEmit`、`vite build` 通过；vitest `62 passed`；eslint 0 errors（仅既有 CreativeStage Fast Refresh warning）。
- PostgreSQL 集成：`TEST_PG_ENABLED` 未设置且 `127.0.0.1:5432` 不可达，integration `6 passed / 17 skipped`，PG 用例如实 skip。
- 真实 Provider 付费调用：未授权，全程零网络假 runtime 验证。