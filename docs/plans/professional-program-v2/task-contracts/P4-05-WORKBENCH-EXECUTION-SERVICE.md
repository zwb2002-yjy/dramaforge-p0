# Task: P4-05 WorkbenchExecutionService（Phase 4 Manual Production Alpha）

## Status

- **State:** COMPLETE
- **Task id:** `p4-05-workbench-execution-service`
- **Program order:** P4-04（COMPLETED）→ **P4-05 WorkbenchExecutionService（本任务）** → P4-06 → …
- **Task boundary:** 实现 `backend/app/production/workbench_execution.py`：Build Plan、Freeze inputs、resolve graph、Create NodeRun、Persist snapshot、Dispatch worker；禁止 legacy 预算/代理审批/直接 Provider HTTP。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §16 P4-05
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §35 Task P4-05
- P4-01 `execution_plan.py`、P4-02 `reference_intents.py`、`ExecutionModelResolver`、`GraphService`、`NodeRun`

## 依据（03 §35 / 07 §16）

- 职责：Build Plan、Freeze inputs、Resolve graph、Create NodeRun、Persist snapshot、Dispatch worker。
- 禁止：direct Provider HTTP、`require_legacy_execution_allowed`、BudgetAuthorization、自动 Model fallback、Agent approval。
- Plan 输入/输出沿用 P4-01（`ExecutionModelResolution` + mode_id + revision identity + translation report）。

## Owned paths

- `backend/app/production/workbench_execution.py`
- `backend/tests/unit/test_workbench_execution.py`
- `docs/plans/professional-program-v2/task-contracts/P4-05-WORKBENCH-EXECUTION-SERVICE.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-07 API 层（execution-plan / executions 端点）。
- 真实 Provider 调用（Worker 侧执行）。
- 修改 03/07 方案正文。

## Verification gate（本任务完成标准）

- `build_plan`：解析成功→冻结计划（fingerprint）；解析 UNAVAILABLE→fail-closed（不建 NodeRun）；存在 capability gap（未接受）→fail-closed。
- `create_and_dispatch`：GraphService 建图（scope_type=shot）→ NodeRun（status=queued）→ snapshot 含 plan_fingerprint 且无 secret；不产生 ProviderOperation、不使用 legacy budget/agent gate。
- unit `test_workbench_execution.py` 通过；后端全量 unit 无回归；ruff/mypy/guardrails 通过。
