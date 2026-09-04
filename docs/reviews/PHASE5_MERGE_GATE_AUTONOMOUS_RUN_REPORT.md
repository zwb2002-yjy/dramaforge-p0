# Phase 5 Merge Gate — Unified Media Production (engineering-gap + verification)

> 依据 `D:/DramaForge_dev_架构收敛设计与执行方案_V2_执行契约版.md` Phase 5 执行。
> Owner 选定 scope：**「补工程 gap + 验证（推荐）」**——不新增真实 Provider 调用、不花新的 Provider 钱；复用既有 old-HEAD 真实 Provider golden 证据，标注 repro 非自动化。

## 总体结论

```text
PHASE_5_GATE = PASSED
READY_FOR_PHASE_6 = YES
```

- Start HEAD：`550aa7c`（Phase 4 收口）
- End HEAD：本报告提交时（见下方 commit）
- Migration Head：`20260827_0049`（**无新增迁移**——Part B 已取消回退）
- 测试证据：backend unit **965 passed**（含新增 freeze dispatch 用例）；PG integration **34 passed**（含新增 3 条重启恢复/冻结证据）；零真实 Provider 调用。

## 本轮解决的工程 gap

### Part A — P0 dispatch 冻结 `model_binding_id`（V2 §Phase 5「Provider/Binding 什么时候冻结」）

- 变更：`backend/app/execution/shot_review.py`
  - 新增 `_freeze_execution_model_resolution()`：在 `start_shot_nodes` 为 keyframe/video 节点用 `ExecutionModelResolver`（与执行路径同一个 resolver）解析具体 binding，并把 `model_binding_id` + 完整 `execution_model_resolution`（binding/connection/connection-revision/credential-revision/catalog-entry/manifest-hash/invoke-value）写进 NodeRun `input_snapshot`。
  - **解析不可用时不阻塞 dispatch**：记录 `model_binding_id: None` + `model_resolution_unavailable_reason`，执行期由既有的 `MODEL_BINDING_UNAVAILABLE` 路径 fail-closed（绝不静默换模型 Y）。
  - experiment override（`model_binding_id` + `model_binding_node_key`）优先于 resolver freeze（保持既有语义）。
- Worker 侧无需新逻辑：`_execute_unified_media_node_run` 已把 snapshot 的 `model_binding_id` 作为 `explicit_binding` 传入 `ModelSelectionIntent`，且 selection 服务已强制 `plan.model_binding_id != frozen_binding_id → MODEL_BINDING_SNAPSHOT_MISMATCH`。
- 证据：`tests/unit/test_product_path_shipped.py` 新增 2 例（freeze 命中 / 无 binding 记录审计标记）；`test_phase5_restart_recovery_pg.py::test_old_task_never_reads_new_binding_pg` 端到端证明「旧任务不读新 Binding」。

### Part B — ~~pricing snapshot 冻结~~ **已取消（Owner 确认，非延期）**

- Owner 指令：「Part B 回退，同时修 V2。不是延期 Part B，而是取消它作为当前 Phase 5 必须项。」
- 代码全部回退（模型列、migration、op 写入、测试断言），`git diff` 无残留。
- **V2 文档已修订两处**：
  1. Phase 5 Gate 检查清单移除「费用可追踪」，并加修订注记（2026-08-29，Owner 确认）；
  2. 歧义表「成本如何认定」行标注当前 Phase 5 不执行。
- 影响：Phase 5 Gate 不再要求费用可追踪；待真实 Provider 链恢复且决定记录成本时单独定稿。

### Part C — PG 重启恢复/冻结证据

新增 `backend/tests/integration/test_phase5_restart_recovery_pg.py`（真实 PostgreSQL，`TEST_PG_ENABLED=1`）：

| 测试 | 覆盖 Gate 项 | 断言 |
|---|---|---|
| `test_worker_restart_requeues_resumable_unified_run_pg` | Worker 重启可恢复 | `recover_interrupted_provider_jobs` 通过真实 `app.resumable_provider_node_run_contexts()` SQL 函数 + RLS scope 路径，把 running 的 unified run 重新 queued、写入 `provider_poll_resume_count=1` + `provider-resume-*` generation，op 的 remote id/attempt 不变；`enqueue` 精确一次 |
| `test_api_restart_outbox_reenqueues_pending_node_run_pg` | API 重启不丢任务 | 持久 Outbox 行被 claim + publish；同一 resolver 确认该 run 可被 re-enqueue（no task lost） |
| `test_old_task_never_reads_new_binding_pg` | 旧任务不会读取新的 Binding | dispatch 冻结 B1；随后项目改指向 B2；执行旧 run 仍以 B1 提交（op.model_binding_id==B1、compiled model==B1 invoke value） |

> 共享 PG 幂等性处理：remote_id / catalog model_id 均加 per-run uuid 前缀，测试可重复执行。

## Phase 5 Gate 清单（V2，含修订）

| Gate | 证据 | 状态 |
|---|---|---|
| 用户选择 X，实际执行就是 X | selection/eligibility 链 + **dispatch 冻结 `model_binding_id`** + worker `explicit_binding`（PG 测试证明旧 run 用 B1 而非 B2） | **PASS** |
| Provider 账户版本可追踪 | `execution_identity`（connection/credential revision）既有 + dispatch 冻结 `execution_model_resolution` | **PASS** |
| 请求参数可追踪 | `request_fingerprint` + `effective_request` + `translation_report`（既有） | **PASS** |
| ~~费用可追踪~~ | **已从 Phase 5 取消**（V2 修订，Owner 2026-08-29）——依赖真实 Provider 账单/fetch_cost，本轮不产生该证据 | **N/A（取消）** |
| Artifact 可追踪 | `get_or_create_artifact` + `produced_by_run_id`（既有） | **PASS** |
| Worker 重启可恢复 | 既有 SQLite 单测 + **新增 PG 测试** | **PASS** |
| API 重启不丢任务 | 既有 Outbox→Arq 链 + **新增 PG 测试** | **PASS** |
| 旧任务不会读取新的 Binding | 既有 `frozen_identity` resume + **新增 PG 端到端测试** | **PASS** |
| Formal Artifact 必须人工确认 | 既有 promote 需显式动作（Phase 4 已证，不在本轮重扩 scope） | **PASS（继承）** |

## 真实 Provider 证据（复用，repro 非自动化）

- `docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-08-27.json`：真实 Agnes keyframe + video，`paid_provider_calls: 2`，`source_commit: 01b53c0`，`provider_raw_cost_fields: []`。
- `docs/reviews/WORKFLOW_V1_5_REAL_PROVIDER_GOLDEN.json`：真实 two-character/action 工作流 golden，`source_commit: d3d945f`。
- **明确声明**：上述真实 2-call 运行发生在 old-HEAD（`01b53c0` / `d3d945f`），**非当前 HEAD 自动重跑**。本轮当前-HEAD 证据是工程 gap 修复（dispatch 冻结 + 重启恢复），由 mock/plugin 测试验证，**零真实 Provider 调用、零新增 Provider 花费**。Phase 5 Gate「至少一次真实 Provider 调用与真实 Artifact 证据」由复用证据 + 本轮工程修复共同构成，repro 未自动化。

## 回归证据

- backend unit：**965 passed**（含新增）。
- PG integration：**34 passed**（含新增 3 条）。
- ruff：`app/` + `tests/` 通过。
- 无前端改动、无 OpenAPI 合同变更、无新增迁移。

## 推荐 Commits

```text
fix(production): freeze model_binding_id at P0 shot dispatch (V2 §Phase 5)
test(production): PG restart-recovery + old-task-never-reads-new-binding evidence
docs: record Phase 5 gate — engineering gaps fixed, cost tracing cancelled (Owner 2026-08-29)
```

## Phase 6 前置（下一阶段，非本 Gate）

V2 §Phase 5 收口后进入 Phase 6 — Review / Repair：candidate/formal 分离、repair 新 Run/不覆盖历史、formal selection 显式记录。真实 Provider 链恢复运行时，再按 Owner 决定补费用证据。
