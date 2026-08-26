# Task: P2 — Phase 2 结构化资产、版本与 `@资产`（AssetVersionReference / AssetTag / ShotReferenceBinding / @Asset 解析）

## Status

- **State:** IN PROGRESS
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

## Verification gate

- `promote` 原子性、唯一 formal、跨项目隔离、rejected 不可 promote 测试通过。
- CharacterReference 兼容回填 + 合并读取不重复、未知 kind → `primary` 测试通过。
- Tag 创建/绑定/过滤 + recycle/restore 测试通过。
- ShotReferenceBinding 来源 XOR、purpose 词表、pinned old version、改名后绑定仍有效测试通过。
- `@Asset` 解析服务输出可映射到 `ExecutionIdentityReference`（role + artifact_id）。
- 后端全量 unit、`ruff`、`mypy`、directory compliance、编译、迁移链/offline SQL 通过；前端 `tsc`/`vite build`、vitest、eslint 通过；Playwright 既有用例通过。
- PostgreSQL 集成仅在可达时执行，否则如实 skip；零真实 Provider 调用。
