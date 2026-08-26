# Task: P2 — Phase 2 结构化资产、版本与 `@资产`（AssetVersionReference / AssetTag / ShotReferenceBinding / @Asset 解析）

## Status

- **State:** COMPLETE
- **Program order:** Professional P0 → Phase 1 (P1) → **Phase 2 (P2)** → Phase 3 (P3) → MS0 → MS1-R → MS1-C → MS2 → MS3 → MS4-LITE → MS5-R → MS5-IDENTITY-A/B/C → Phase 4 Merge Gate → P4
- **Task boundary:** 完成 07 §4 Phase 2 全部组件：AssetVersion 生命周期服务、AssetVersionReference、AssetTag/AssetTagLink、ShotReferenceBinding、`@Asset` UUID 解析与前端引用。不进入 Phase 3（Scene Wall/Scene Workspace/Shot Workbench）、不调用真实模型。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §4 Phase 2（含验收：ShotReferenceBinding 保存业务 purpose 而非 provider role）
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §15–§21（P2-01..P2-06 与 Phase 2 Gate）
- [`../02-DRAMAFORGE_PRO_DESIGN.md`](../02-DRAMAFORGE_PRO_DESIGN.md) §10 AssetVersionReference、§11 AssetTag、§13 @资产、§14 ShotReferenceBinding、§14.1 执行时冻结
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) §9（resolved_references 进入执行身份，P2 只建立解析服务，消费在 P4）
- Completed `P1-PROFESSIONAL-WORKSPACE-FOUNDATION.md`（AssetVersion/Asset.current_version_id 已在 P1 落库）

## Current evidence / drift

- `AssetVersion` 与 `Asset.current_version_id` 已存在（P1 迁移 `20260826_0043`）；`backend/app/api/v1/assets.py` 已有 list/create/update/versions。
- 尚无 `version_service.py`、`tag_service.py`、`asset_card_service.py`；AssetVersion 目前只有 draft 状态，没有 candidate/formal/historical/rejected 生命周期与原子 promote。
- `CharacterReference` 仍在 `characters.py` 使用（P0 兼容 API）；尚无 AssetVersionReference、AssetTag/AssetTagLink、ShotReferenceBinding。
- 执行身份 `ExecutionIdentitySnapshot.resolved_references: list[ExecutionIdentityReference]`（role + artifact_id）已冻结；P2 的 @Asset 解析输出应能映射到该结构，但消费/写入 NodeRun 在 P4。

## Implementation summary（子任务）

1. **P2-01 AssetVersion 生命周期**：`backend/app/assets/version_service.py` 提供 `create_candidate` / `promote` / `reject` / `list_history` / `resolve_current`；`promote` 原子事务（old formal → historical，candidate → formal，`Asset.current_version_id` → candidate，`Asset.version += 1`）；状态词表 candidate/formal/historical/rejected。测试 `test_asset_version_promotion.py`（唯一 formal、旧版本不删、rejected 不可 promote、cross-project 拒绝、并发 promote 不产生双 formal）。
2. **P2-02 AssetVersionReference + CharacterReference 兼容**：新增 `AssetVersionReference`（asset_version_id / artifact_id / reference_role / label / sort_order / metadata）；迁移对现有 Character 回填 AssetVersion v1 与 AssetVersionReference（`is_canonical` → `primary` 或 `front_face`，未知 kind → `primary`），并设置 `Asset.current_version_id`；`AssetCardReadService` 在迁移期合并新 Version Reference 与旧 CharacterReference（只读未迁移部分），禁止重复返回同一 Artifact。不删除 `CharacterReference`。
3. **P2-03 AssetTag / Recycle**：新增 `AssetTag`（(project_id, normalized_name) 唯一）与 `AssetTagLink`；API `POST /projects/{id}/asset-tags`、`PUT /projects/{id}/assets/{asset_id}/tags`、`POST .../recycle`、`POST .../restore`；list 支持 kind/tags/status/name substring 过滤。
4. **P2-04 Asset API / Asset Cards / from-artifact**：`POST /projects/{id}/assets/from-artifact`（显式“加入资产”，生成结果绝不自动成为 Asset）；`frontend/src/features/assets/` 资产卡列表（标签过滤、回收/恢复入口）。
5. **P2-05 ShotReferenceBinding**：`backend/app/production/models.py` 新增 ORM；来源 XOR（asset / pinned asset version / direct artifact 至少一种，CHECK 约束）；purpose 词表 12 项（identity/clothing/scene_layout/scene_lighting/style/action/pose/camera_language/audio_rhythm/first_frame/last_frame/generic_reference）；`resolution_mode` current_formal/pinned_version/direct_artifact；service + API（create/list/pin old version）；`version` 乐观并发。
6. **P2-06 `@资产` 前端引用**：`AssetMentionInput.tsx` / `AssetReferencePicker.tsx`，autocomplete 选中真实 Asset 后才建立 Binding（未绑定手打 `@` 显示“未解析引用”）；重命名 Asset 不使既有 Binding 失效（绑定存 UUID，不依赖 prompt 文本）。

## Owned paths

- `backend/app/assets/models.py`
- `backend/app/assets/version_service.py`
- `backend/app/assets/tag_service.py`
- `backend/app/assets/asset_card_service.py`
- `backend/app/production/models.py`
- `backend/app/api/v1/assets.py`
- `backend/app/api/v1/references.py`
- `backend/app/api/v1/router.py`
- `backend/alembic/versions/20260826_0044_phase2_asset_references.py`
- `backend/tests/unit/test_asset_version_promotion.py`
- `backend/tests/unit/test_asset_version_reference_compat.py`
- `backend/tests/unit/test_asset_tags_recycle.py`
- `backend/tests/unit/test_shot_reference_binding.py`
- `backend/tests/unit/test_asset_reference_resolution.py`
- `frontend/src/features/assets/**`
- `frontend/src/components/assets/AssetMentionInput.tsx`
- `frontend/src/components/assets/AssetReferencePicker.tsx`
- `frontend/src/routes/projects.$projectId.assets.tsx`
- `docs/plans/professional-program-v2/task-contracts/P2-PHASE2-ASSET-REFERENCES.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- Phase 3（Scene Wall / Scene Workspace / Shot Workbench / Canvas / Asset bindings UI）。
- P4 WorkbenchExecutionPlan 对 resolved_references 的执行期消费。
- 语义搜索 / embedding / 自动推荐；真实 Provider / 付费调用。
- 删除 `CharacterReference` 或旧 `/characters/lead` 兼容 API。
- 额外总规划或并行改写共享 Schema。

## 完成证据（实现摘要）

- **P2-01**：`backend/app/assets/version_service.py`（create_candidate/promote/reject/list_history/resolve_current）；promote 原子地把旧 formal→historical、candidate→formal、`current_version_id` 指向候选；`test_asset_version_promotion.py` 覆盖唯一 formal、旧版本不删、rejected 不可 promote、跨项目隔离。
- **P2-02**：`AssetVersionReference` ORM + 迁移 `20260826_0044` 对现有 Character 回填 AssetVersion v1（formal）+ AssetVersionReference（canonical→primary/known kind 保留/未知→primary）并设置 `current_version_id`；`AssetCardReadService` 迁移期合并读取（version 优先、legacy 仅补缺、同一 Artifact 不重复返回）；`CharacterReference` 未删除。
- **P2-03**：`AssetTag`/`AssetTagLink` + `tag_service.py`；`POST /asset-tags`、`PUT /assets/{id}/tags`、`POST recycle/restore`；`GET /assets` 支持 kind/status/name/tags 过滤。
- **P2-04**：`POST /assets/from-artifact` 显式“加入资产”（生成结果绝不自动成为 Asset）；`frontend/src/features/assets/` 资产卡面板（标签过滤、版本、回收/恢复、候选提升）。
- **P2-05**：`ShotReferenceBinding` ORM（来源 XOR CHECK、purpose/stage/resolution_mode CHECK、版本乐观锁）；`backend/app/api/v1/references.py` CRUD + resolve；业务 purpose 词表 12 项，不存 provider role。
- **P2-06**：`AssetMentionInput.tsx` / `AssetReferencePicker.tsx`；autocomplete 选中真实 Asset 才建立 Binding，未绑定手打 `@` 显示“未解析引用”；`test_asset_reference_resolution.py` 证明 current_formal 链、pinned_version 冻结、Asset 改名后绑定仍有效（UUID 绑定）。

## Verification gate（全部通过）

- 后端全量 unit：`738 passed / 1 warning`（+11 个 P2 测试）；P2 focused `11 passed`；`ruff`、`mypy`(193)、`compileall`、directory compliance、`git diff --check` 通过。
- 迁移链单 head `20260826_0044`，offline `alembic upgrade head --sql` 生成/编译通过（含回填 SQL）。
- 前端：`tsc --noEmit`、`vite build` 通过；vitest `68 passed`（+6 个 P2 组件测试）；eslint 0 errors（仅既有 CreativeStage Fast Refresh warning）；Playwright `8 passed`。
- PostgreSQL 集成：`TEST_PG_ENABLED` 未设置且 `127.0.0.1:5432` 不可达，integration `6 passed / 17 skipped` 如实 skip；零真实 Provider 调用。
- `@Asset` 解析输出（purpose/role/artifact_id/source/asset_id/asset_version_id）可映射到 `ExecutionIdentityReference`；执行期消费留待 P4。

> 台账说明：`frontend/tests/unit/AssetMentionInput.test.tsx`、`AssetReferencePicker.test.tsx` 属测试目录，随实现提交登记（非台账 HEAD 证据提交）。
