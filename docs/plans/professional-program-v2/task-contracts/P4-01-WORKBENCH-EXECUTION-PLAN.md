# Task: P4-01 WorkbenchExecutionPlan（Phase 4 Manual Production Alpha）

## Status

- **State:** IN PROGRESS
- **Task id:** `p4-01-workbench-execution-plan`
- **Program order:** Phase 4 Merge Gate（PASSED）→ **P4-01 WorkbenchExecutionPlan（本任务）** → P4-02 → … → P4-11 → §17 Golden Professional Test
- **Task boundary:** 只建立 P4-01 纯 Pydantic 合同（`WorkbenchExecutionPlan` / `CapabilityGap` / `ControlTranslation` / `PlannedReference`）；不实现编译器、不接 API、不改 Provider 调用。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §16 P4-01
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §31 Task P4-01

## 依据（07 §16 + 03 §31）

- 新增 `backend/app/production/execution_plan.py`（纯 Pydantic）。
- 建立 `WorkbenchExecutionPlan`、`CapabilityGap`、`ControlTranslation`。
- `ResolvedReference` 改名 `PlannedReference`（避免与 `app.providers.runtime.ResolvedReference` 冲突）。
- Plan 输入增加 `ExecutionModelResolution` + `mode_id`。
- Plan 输出增加：model resolution、connection revision、credential revision identity、translation report。
- Plan 输出（03）：stage、prompt、semantic intent、resolved references、resolved model、capability、exact/approximate/unsupported controls、semantic request preview。
- 禁止：任何 secret / provider wire payload 进入 Plan。

## Owned paths

- `backend/app/production/execution_plan.py`
- `backend/tests/unit/test_execution_plan.py`
- `docs/plans/professional-program-v2/task-contracts/P4-01-WORKBENCH-EXECUTION-PLAN.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-02 ReferencePlanCompiler（下一任务）。
- P4-05 WorkbenchExecutionService / API。
- 任何 Provider 调用或真实模型执行。
- 修改 07/03 方案正文。

## Verification gate（本任务完成标准）

- `execution_plan.py` 纯 Pydantic，无 ORM/IO/服务。
- `PlannedReference` 与 `app.providers.runtime.ResolvedReference` 命名不冲突。
- `WorkbenchExecutionPlan` 携带 `ExecutionModelResolution` + `mode_id` + connection/credential revision identity + `TranslationReport`。
- fingerprint 确定性（同输入同指纹）；`freeze()` 幂等。
- JSON 序列化不含任何 secret 字段（api_key / authorization / ciphertext / credential）。
- unit `test_execution_plan.py` 通过；后端全量 unit 无回归；ruff/mypy/guardrails 通过。
