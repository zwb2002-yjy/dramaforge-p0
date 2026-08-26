# V1 Release Gate Report（03 §95）

- **日期：** 2026-08-27
- **分支 / HEAD：** `dev`（本报告对应最近一次全矩阵运行）
- **依据：** `docs/plans/professional-program-v2/03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md` §95
- **范围：** Professional 七方案（Phase 1–10）全部交付后的 V1 发布门核对。

## 验证矩阵（2026-08-27 实测）

| 项 | 命令 | 结果 |
|---|---|---|
| Backend static | `ruff check backend/app backend/tests backend/alembic scripts` | All checks passed |
| Backend static | `mypy app` | 215 source files, no issues |
| Backend static | `compileall backend/app scripts` | OK |
| Backend unit | `pytest tests/unit` | **831 passed** |
| PostgreSQL integration | `TEST_PG_ENABLED=1 pytest tests/integration --fail-on-skip` | **29 passed**（真实 PG，迁移 head `20260827_0049`） |
| Frontend lint | `eslint .` | 0 errors（2 既有 warning） |
| Frontend type | `tsc --noEmit` | OK |
| Frontend test | `vitest run` | **91 passed** |
| Frontend build | `vite build` | OK |
| Playwright | `playwright test` | **14 passed**（含 P10-07 5 个新 V1 spec） |
| Golden real-provider run | `scripts/prove_phase4_golden_professional.py` | **环境门控，未实跑**（需重建 compose → 迁移 dev 库 0040→0049 → 真实 Agnes/DeepSeek 付费调用；见文末） |

## §95 逐条核对

### 架构
- Project / Scene / Shot 仍一套：P3 场景/镜头 ORM 单一事实源（`app/assets/models.py`），Phase 4–9 未建第二套 Project/Scene/Shot。
- Model Capability 仍一套：`app/providers/manifest.py` + `ModelCapabilityManifest`，workbench 计划冻结 manifest hash。
- Runtime 仍一套：NodeRun → Outbox → Worker → ProviderOperation → Artifact（P0 内核复用，双入口单内核，03 §100）。
- Artifact 仍一套：`artifacts` 表统一承载 keyframe/video/composite；formal 指针（`Shot.formal_*_artifact_id`）只读引用。
- 证据：`test_phase10_migration_audit_pg.py`（历史项目经新 Workbench 全量可读）、`test_v3_boundary.py`（业务代码不 import 具体 provider）。

### 手动生产
- Director Assistant 关闭也能完成：`director_controlled=false` 时 workbench 直接启动/重跑（`startProfessionalShot` / `rerunProfessionalShot`）；P7 Gate 证明 Proposal 未确认不执行、手动编辑优先。
- 不依赖旧 Budget Gate：e2e `professional-manual` 断言生产页无 `预算|计费|费用` 文本；`test_phase10_professional_resolution_no_bypass_pg` 证明 dispatch 无 budget/agent gate。
- 不依赖 Quick：`/quick` 已改为 Legacy 说明页（P10-01），e2e/单测断言不 redirect。
- 证据：`professional-manual.spec.ts`、`DirectorWorkspace.test.tsx`、`WorkstationShell.test.tsx`。

### 资产
- 多版本 / Formal / Candidate：`asset_versions` 不可变版本 + `current_version_id`；experiment candidate 与 formal 分离。
- `@资产`：AssetReferencePicker + `@引用`（e2e `director_workflow` / `professional-edit`）。
- 历史执行冻结 / old-version warning：`expected_version` 乐观锁；P7 stale 机制（手动改版后 proposal stale、accepted 记录 failed 不执行）。
- 证据：`test_asset_version_promotion.py`、`test_proposal_stale_panel.py`、RLS audit（asset_versions FORCE RLS）。

### 模型
- Manifest 动态 UI：workbench 按模型 capabilities 渲染「动态能力」（e2e `professional-experiment`）。
- local override：requested_model_id / requested_binding_id 经 `ExecutionModelResolver` request_override 源。
- 模型切换实验：Phase 5 实验分支（e2e `professional-experiment`）。
- unsupported 不静默：`build_plan` 对 capability_gaps fail closed；`require_formal_keyframe` NO_FORMAL_KEYFRAME fail closed。
- 证据：`test_execution_model_resolution_pg.py`、`test_phase10_professional_resolution_no_bypass_pg.py`。

### 实验
- 正式/实验完全隔离：`ProductionExperiment`/`ShotExperiment` 不触碰 formal；采纳显式复制（P5-06）。
- 可局部采纳：`adoption_scope`（current_node / keyframe_rerun_downstream）。
- 证据：`professional-experiment.spec.ts`、Phase 5 Gate、RLS audit。

### 审片
- 图片 Region：`image_region` 批注（x/y/width/height）持久化（e2e `professional-review`）。
- 视频时间范围：`video_time` 批注（time_start/time_end）（e2e `professional-review`）。
- 两种 V1 Repair：`rerun_video` / `regenerate_keyframe_then_video`（`RepairService.build_repair_plan`，Golden project 验证 `repair_suggested`）。
- 证据：`professional-review.spec.ts`、`test_phase10_golden_project_pg.py`。

### 导演智能体
- Proposal first / Partial apply / Stale / 用户手改优先：P7 Gate（接受 2 拒绝 1、model 不变、version 正确、手动改版后 stale）。
- 证据：`test_proposal_stale_panel.py`、`director-assistant.spec.ts`。

### 导演台
- 2D：`DirectorBoard2D` SVG 画布 + `Scene.design_state.blocking_2d`（P8 Gate、Golden project、`director-assistant.spec.ts`）。
- 粗 3D：`mode="rough_3d"` 数据层（P8 Gate 以数据结构层覆盖；three 依赖未安装，标为后续依赖步）。
- Camera / Pose / Gaze：`DirectorControlPackage` 控制类型（P8）。
- 可跳过：`accepted_approximations` / 直接生成（P8 Gate）。
- 证据：`test_phase8_gate.py`、`DirectorBoard2D.test.tsx`。

### 剪辑
- OpenCut / Editing Adapter：P9 `EditingAdapter`（create/load/save/export）+ `edit_sessions` 持久化；e2e `professional-edit` 展示 OpenCut manifest。
- Production fact 不被 Timeline 覆盖：`production_lineage` 只读；`Shot.formal_*` / `Asset.current_version` / `ProductionGraph` 不被编辑改动（P9 Gate）。
- 证据：`test_editing_gate.py`、`professional-edit.spec.ts`。

### 验证
- 上表全矩阵通过；Golden real-provider run 环境门控（见下）。

## Golden real-provider run（环境门控项，未实跑）

§95 验证节要求「Golden real provider run」。当前运行栈为旧镜像（postgres `20260827_0040`，无 Phase 4–9 端点），需按以下步骤执行（涉及真实 Agnes/DeepSeek 付费调用）：

1. 重建 compose（新镜像 / 迁移到 `20260827_0049`）。
2. 对 dev 库执行 `alembic upgrade head`。
3. 运行 `scripts/prove_phase4_golden_professional.py`（真实 Agnes/DeepSeek）。
4. 证据写入 `docs/reviews/`。

**状态：未执行——不伪称通过。** 代码路径已由 `test_phase10_professional_resolution_no_bypass_pg.py`（resolver 冻结 resolution → worker 消费）与 `test_execution_model_resolution_pg.py`（真实 PG 快照往返）覆盖。

## 结论

除「Golden real-provider run」环境门控项外，V1 Release Gate 全部子项均有自动化证据支持，当前 `dev` 全矩阵通过。
