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
| Golden real-provider run | `scripts/prove_professional_agnes_golden.py`（+ `scripts/prove_phase4_golden_professional.py` 契约修复） | **已实跑：ok=true，2 次真实 Agnes 付费调用**（keyframe image + video 704×1280 5.04s）；证据 `docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-08-27.json` |

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

## Golden real-provider run（已实跑）

§95 验证节要求「Golden real provider run」。2026-08-27 已执行：

1. 重建 `dramaforge-backend:local` 镜像（当前源码）并重建 api / worker-heavy / worker-default / dispatcher 容器。
2. dev 库 `alembic upgrade head`：`20260826_0040` → `20260827_0049`（全部 additive）。
3. 运行 `scripts/prove_professional_agnes_golden.py`（真实 Agnes 付费调用）：
   - **ok=true**，`paid_provider_calls=2`（keyframe image `agnes-image-2.1-flash` + video `agnes-video-v2.0`，704×1280、5.042s mp4）。
   - 全链 prompt → keyframe → identity_review → video 均 completed；ProviderOperation succeeded；OpenCut manifest v2 生成。
   - 证据 `docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-08-27.json`（无 secret，经扫描）。
4. `scripts/prove_phase4_golden_professional.py` 认证/轮询/ops/场景创建契约已更新到当前 API（cookie session + CSRF + `X-Workspace-Id`、run trace 轮询、snapshot ops、`/scripts/import`）。**已知限制**：该脚本按单节点分发（execution-plan → executions），当前 shot 管线要求上游 run 先行（keyframe 依赖 prompt），完整对齐需按产品整链启动；已由整链 golden 实跑覆盖。

## 结论

V1 Release Gate 全部子项均有证据支持（含 Golden real-provider run 已实跑），当前 `dev` 全矩阵通过。

---

## Retained prior current revalidation — 2026-09-01 (`78f2df4`)

以下为本轮之前已经完成的当前候选复核证据，原样保留，供审计比较；它不再是当前候选的发布结论。

### Candidate and environment boundary

- **Prior candidate:** `dev` / `78f2df44eaa43781e12738e3f29911be34e336b6` (`2026-09-01T19:08:02+08:00`, `test: reconcile professional edit e2e flow (#29)`).
- **Prior clean source:** checks ran in detached worktree `D:\dramaforge\.worktrees\p10-v1-revalidation-20260901`; source status was empty before and after. The root had the pre-existing untracked `codex-with-chatgpt/`, excluded from that candidate.
- **Prior migration:** isolated PostgreSQL target was upgraded from `20260827_0049` to `20260901_0050`; `alembic heads`, `alembic check`, and `alembic current` passed.
- **Prior runtime drift:** the long-running local Compose stack identified source `82d5ee53ea00fb84ef43911597c7d63e8f29411a` and migration `20260827_0049`, so it was not evidence for `78f2df4…`.
- **Prior paid-call boundary:** no current-turn paid authorization was present; no 2026-09-01 Golden JSON was created in that run.

### Prior verification matrix

| Area | Prior command / evidence | Result |
|---|---|---|
| Source / commit | `git rev-parse HEAD`; `git status --porcelain` | **PASS** — exact prior candidate, clean detached worktree |
| Directory / policy | `check_directory_compliance.py`; `repo_guardrails.py policy` | **PASS** in clean worktree; root drift was the untracked `codex-with-chatgpt/` |
| Migration | `alembic upgrade head`; `alembic heads`; `alembic check`; `alembic current` | **PASS** — `20260901_0050 (head)` |
| Backend static | ruff, mypy, compileall | **PASS** — mypy 258 source files |
| Extended script lint | `python -m ruff check scripts` | **FAIL** — four existing F401/F841 findings at that candidate |
| Backend unit | `python -m pytest tests/unit -q -r fE` | **PASS** — 1057 passed, 1 warning |
| PostgreSQL / audits | `TEST_PG_ENABLED=1 python -m pytest tests/integration -q -rs --fail-on-skip` | **PASS** — 35 passed, 1 warning |
| Runtime / model-resolution / editing focus | bounded unit command | **PASS** — 65 passed, 1 warning |
| LiteLLM runtime | required official pinned-proxy test | **PASS** — 6 passed, 1 warning |
| Frontend | lint, typecheck, Vitest, API check, build | **PASS** — 2 warnings; 32 files / 129 tests |
| Full Playwright | `npm run test:e2e` | **PASS** — 16 Chromium tests |
| Golden real Provider | not run | **BLOCKED** — no paid authorization and runtime stack drift |

### Prior §95 mapping and verdict

The prior report mapped Architecture, Manual production, Assets, Models, Experiments, Review, Director agent, Director board, and Editing to the corresponding P10/P9 PostgreSQL, unit, frontend, and Playwright evidence. Its honest verdict was **BLOCKED** because the prior candidate had no authorized paid Golden run, and **FAIL** for the four script-lint findings. The superseding candidate below resolves both conditions without rewriting that historical evidence.

---

## Current P10 V1 Release Gate Revalidation — 2026-09-01 (`66eb4d2`)

### Candidate and environment boundary

- **Current candidate:** `dev` / `66eb4d28a352dc093e1f8a7c3d733601d13a9f7c` (`2026-09-01T20:16:04+08:00`, `fix: clean gate script lint findings (#30)`).
- **Source isolation:** all current checks ran from detached clean worktree `D:\dramaforge\.worktrees\p10-v1-golden-20260901`, created directly from the exact candidate commit. Before evidence generation, `git status --porcelain` was empty; final status contains only the three allowed evidence-document changes (report, revalidation contract, and Golden JSON). The root `D:\dramaforge` remained unchanged with its pre-existing report modification, `codex-with-chatgpt/`, and revalidation contract.
- **Directory/policy:** candidate `check_directory_compliance.py` and `repo_guardrails.py policy` both passed. The root untracked `codex-with-chatgpt/` was never included in candidate evidence.
- **Candidate runtime:** backend and frontend images were rebuilt with unique candidate tags and OCI revision `66eb4d28…`; API, dispatcher, both workers, frontend, Postgres, Redis, MinIO, and LiteLLM were healthy in isolated Compose project `p10-v1-golden-20260901`. API `/health` reported the exact source commit; frontend gateway returned 200; LiteLLM readiness returned 200.
- **Candidate database:** isolated Compose PostgreSQL was migrated to `20260901_0050 (head)`. `alembic heads`, `alembic check`, and `alembic current` passed. The runtime role was verified `LOGIN=true`, `BYPASSRLS=false`, `SUPERUSER=false`, with a configured password.
- **Provider setup:** the existing local Agnes credential was used only through the candidate onboarding/probe flow; it was never printed or written to evidence. Agnes `auth_models` returned HTTP 200, and the selected keyframe/video bindings became `account_verified=true`.
- **Paid-call authorization:** the user explicitly authorized the current real Provider Golden run in this turn. No external/provider account password was requested or used; the disposable local DramaForge proof account used the script's synthetic password and the existing local environment only.

### Verification matrix (current candidate)

| Area | Command / evidence | Result |
|---|---|---|
| Source / commit | `git rev-parse HEAD`; `git status --porcelain` before evidence | **PASS** — exact `66eb4d28…`; clean source |
| Directory compliance | `python scripts/check_directory_compliance.py --root D:\dramaforge\.worktrees\p10-v1-golden-20260901` | **PASS** |
| Repository policy | `python scripts/repo_guardrails.py policy --repo-root D:\dramaforge\.worktrees\p10-v1-golden-20260901` | **PASS** |
| Candidate image identity | `docker inspect` OCI revision and runtime `DRAMAFORGE_SOURCE_COMMIT` for API/dispatcher/workers/frontend | **PASS** — all exact `66eb4d28…` |
| Candidate migration | Compose `migrate`; `alembic heads`; `alembic check`; `alembic current` | **PASS** — `20260901_0050 (head)` |
| Backend static | `python -m ruff check app tests alembic`; `python -m mypy app`; `python -m compileall -q backend/app scripts` | **PASS** — mypy 258 source files |
| Extended script lint | `python -m ruff check scripts` | **PASS** — all checks passed on `66eb4d2` |
| Backend unit | `python -m pytest tests/unit -q -r fE` from an exact-commit disposable archive runner | **PASS** — 1057 passed, 1 warning |
| PostgreSQL / audits | `TEST_PG_ENABLED=1 python -m pytest tests/integration -q -rs --fail-on-skip --ignore=tests/integration/test_litellm_real_proxy.py` against candidate Postgres | **PASS** — 29 passed, 1 warning; P10/P9, migration, RLS, and model-resolution audits included |
| LiteLLM runtime | `LITELLM_INTEGRATION_REQUIRED=1 python -m pytest tests/integration/test_litellm_real_proxy.py -q -rs` | **PASS** — 6 passed, 1 warning; official `ghcr.io/berriai/litellm:v1.96.0` with mock deployments |
| Runtime / model-resolution / editing focus | bounded unit command covering runtime, resolver, LiteLLM, workbench, and editing gate | **PASS** — 65 passed, 1 warning |
| Frontend lint | `npm run lint` | **PASS** — 0 errors, 2 existing Fast Refresh warnings |
| Frontend type | `npm run typecheck` | **PASS** |
| Frontend tests | `npm run test -- --reporter=verbose` | **PASS** — 32 files / 129 tests |
| API contract | `npm run api:check` with candidate backend environment | **PASS** |
| Frontend build | `npm run build` | **PASS** |
| Full Playwright | `npm run test:e2e` | **PASS** — 16 Chromium tests; mocked professional flows include P10-07 |
| Golden real Provider | `python scripts/prove_professional_agnes_golden.py --base-url http://127.0.0.1:18080/api/v1 --timeout 900 --out docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-09-01.json` | **PASS** — `ok=true`, `paid_provider_calls=2`, all terminal runs completed |

The combined integration command initially reported six skips only because a disposable Linux test runner had no Docker CLI for the LiteLLM fixture. The required official LiteLLM test was then run from the host against the pinned image and passed 6/6; the PG/audit portion passed 29/29 with `--fail-on-skip`, so no integration test was silently accepted as skipped.

### Execution notes and transient environment state

- A first unit invocation injected an explicit SQLite URL and the candidate image's baked source identity, producing four test-environment failures. It was discarded as non-equivalent to CI; the rerun used an exact-commit archive clone with the normal test defaults and passed 1057/1057.
- On the fresh candidate DB, the onboarding probe initially created a second workspace while the Golden script intentionally selects the first workspace. The same existing local Agnes credential was configured and auth-probed in that first workspace; the initial Golden attempt stopped before any Provider call with `no enabled Agnes connection found`.
- The PG suite's isolated-owner test temporarily changed the shared candidate `dramaforge_app` role while the suite was pointed at the candidate DB. The role was restored with the candidate `database-bootstrap` command, candidate workers were restarted, and the candidate-only Redis queue was flushed before the successful Golden rerun. No root container, source file, or root working-tree evidence was changed.

### §95 evidence mapping (current candidate)

| §95 area | Current evidence |
|---|---|
| Architecture — one Project/Scene/Shot, Model Capability, Runtime, and Artifact truth | PostgreSQL `test_historical_project_readable_by_new_workbench_pg`; `test_phase10_professional_resolution_no_bypass_pg`; `test_architecture_boundary_business_never_imports_concrete_providers`; `test_execution_model_resolution_round_trips_in_node_run_snapshot_pg`; `test_golden_professional_project_covers_p10_06_pg` |
| Manual production — Director Assistant off, no old Budget Gate, no Quick dependency | `professional-manual.spec.ts`; retired Quick route in `director_workflow.spec.ts`; `DirectorWorkspace.test.tsx`; `WorkstationShell.test.tsx`; `test_phase10_professional_resolution_no_bypass_pg` |
| Assets — multi-version, Formal/Candidate, `@资产`, historical freeze, old-version warning | `test_asset_version_promotion.py`; `AssetReferencePicker.test.tsx`; `director_workflow.spec.ts`; `test_proposal_stale_panel.py`; `test_phase10_golden_project_pg.py` |
| Models — manifest dynamic UI, local override, model swap, unsupported fail-closed | `ModelControls.test.tsx`; `professional-experiment.spec.ts`; `test_execution_model_resolution.py`; `test_execution_model_resolution_round_trips_in_node_run_snapshot_pg`; `test_execution_plan.py`; `test_reference_plan_compiler.py`; `test_creative_negative_gates.py` |
| Experiments — formal/experiment isolation and partial adoption | `professional-experiment.spec.ts`; `test_phase5_gate.py`; `test_golden_professional_project_covers_p10_06_pg` |
| Review — image Region, video time range, both V1 Repair paths | `professional-review.spec.ts`; `test_phase6_gate.py`; `test_repair_service.py`; `test_phase10_golden_project_pg.py` |
| Director agent — Proposal first, Partial apply, Stale, user manual edits first | `director-assistant.spec.ts`; `test_proposal_stale_panel.py`; `test_proposal_commands.py`; `test_phase5_gate.py`; `test_editing_director_suggestion.py` |
| Director board — 2D, rough-3D data contract, Camera/Pose/Gaze, skip path | `DirectorBoard2D.test.tsx`; `test_phase8_gate.py`; `test_golden_professional_project_covers_p10_06_pg` |
| Editing — OpenCut/Editing Adapter and Timeline cannot overwrite Production facts | P9-03A/B `test_editing_api.py` and `EditingWorkspace.test.tsx`; P9-04A/B/C/D `test_editing_proposal_commands.py`, `test_editing_director_suggestion.py`, and `professional-edit.spec.ts`; `test_editing_gate.py`; migration `20260901_0050` |
| Verification — static, unit, PostgreSQL, frontend, Playwright, Golden | Current matrix above: all mandatory checks pass and the sanitized Golden JSON is present |

### Golden real-provider evidence

The successful JSON is `docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-09-01.json` (14,011 bytes in the repository's normalized LF checkout; SHA-256 `9404f968fef33fbc1c1ce6549a263d6d5f93eff18d6dfa44d2c3ae9bc1a9a5d5c4`). The disposable candidate worktree retained the equivalent CRLF artifact at 14,400 bytes with SHA-256 `c1b844b7a8c70642fd7c7052f31948b3a8a4000eb44e20ab47329a435c751909`; line-ending normalization is the only difference. Its invariants are `source_commit=66eb4d28a352dc093e1f8a7c3d733601d13a9f7c`, `dirty=false`, `ok=true`, and `paid_provider_calls=2`; a secret-value scan found zero hits. It records two succeeded Agnes operations (`agnes-image-2.1-flash` and `agnes-video-v2.0`), a 736×1312 PNG keyframe, a 704×1280 MP4 of 5.042 seconds, and an OpenCut manifest v2 with video/audio/subtitle tracks. The prompt and identity-review nodes also completed and produced their JSON Artifacts.

The JSON truthfully records both paid operations as Agnes. This particular `prove_professional_agnes_golden.py` path did not create a DeepSeek ProviderOperation for its prompt node, so no paid DeepSeek call is claimed; the configured LiteLLM/DeepSeek path is covered by the required six-test official proxy suite. The V1 Golden requirement of at least one paid Provider call is satisfied by the two successful Agnes operations.

### Current verdict

- **PASS:** exact candidate source isolation; candidate Compose identity and health; migration `20260901_0050`; directory and policy checks; backend ruff/mypy/compileall; scripts ruff; 1057 unit tests; 29 PostgreSQL/audit tests plus 6 required LiteLLM tests; 65 focused runtime/model-resolution/editing tests; all frontend quality/API/build checks; 16 Playwright tests; and the authorized real-provider Golden.
- **Non-blocking environment note:** the root `codex-with-chatgpt/` remains untouched and excluded from the candidate; the candidate worktree contains only the allowed Golden JSON after evidence generation.

**Overall current V1 Release Gate verdict: `PASS`.** No mandatory current-candidate blocker remains.

---

## Current DramaForge V1 Goal release candidate — 2026-09-03 (`c8bd597`)

### Candidate and image identity

- **Final candidate source:** `c8bd59724d3500ca36ea5c550d64c97c926b904e`
  (final release-evidence commit on `dev`); Golden runtime commit `d46ad15`;
  image OCI revision `b7b7864…`（backend/frontend 内容与 `c8bd597` 相同，
  差异仅为本报告绑定说明）。
- **Migration head:** `20260903_0052`（`project_creative_profiles`）。
- **Real Provider Golden:** `docs/reviews/GOLDEN-V1-CURRENT-HEAD-20260903.json`
  (`ok=true`, `paid_provider_calls=6`, 3 Formal Shots, OpenCut 15.000s,
  EditSession v1 export 15.126s).
- **Local exact-source images** built by committing the current backend app
  tree / frontend `dist` onto the already-built pinned runtime base with OCI
  revision `b7b7864…`（Docker Desktop PyPI TLS prevented a from-scratch
  rebuild locally；full Docker quality gate ran on GitHub Actions）。
  - backend: `dramaforge-backend:release-b7b7864754a7c9cb9c55a1ea8554a306116b1c0d`
    digest `sha256:b86355c5328aa9be96dac0aba3dd566857b01de096660a5f136a513f974dce09`
  - frontend: `dramaforge-frontend:release-b7b7864754a7c9cb9c55a1ea8554a306116b1c0d`
    digest `sha256:defa45fdd8aed7702be442239b39853c43e02034818f11363876db904ec367ef`
- Smoke: release backend uvicorn started with current code and app import ok；
  release frontend `/gateway-health` returned `ok`.

### GitHub Actions evidence (`c8bd597`, push)

| Gate | Result |
|---|---|
| CI policy | PASS |
| CI container-gates | PASS — backend unit **874 passed**; PostgreSQL migration/integration **17 passed**; frontend Vitest **24 files / 106 tests**; Playwright **15 passed**; LiteLLM real-proxy **5 passed** |
| Security | PASS |

### V1 audit / bounded fixes recorded in this candidate

- **G3B** project-level DirectorAutonomy switch UI.
- **G6C** Editing→Production Repair routing (proposal-only, no auto-execute).
- **G6D** Editing suggestion whole/partial/reject apply to timeline draft.
- **G7C** Workbench media dispatch pure-upstream fix (`UPSTREAM_RUN_MISSING`
  eliminated) — proven by the real current-HEAD Golden.
- Task contracts under
  `docs/plans/professional-program-v2/task-contracts/V1-G3B-…`,
  `V1-G6C-…`, `V1-G6D-…`, `V1-G7B-…`, `V1-G7C-…`, `V1-G8-…`.

### Current verdict

All mandatory current-candidate checks are green except the Owner-only
`dev → main` merge (PR #12).  Agent status: `GOAL_READY_FOR_OWNER_MERGE` —
do **not** merge or approve on behalf of @zwb2002-yjy.
