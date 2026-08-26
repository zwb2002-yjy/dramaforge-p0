# Task: P4-10 Execution Trace（Phase 4 Manual Production Alpha）

## Status

- **State:** IN PROGRESS
- **Task id:** `p4-10-execution-trace`
- **Program order:** P4-09（COMPLETED）→ **P4-10 Execution Trace（本任务）** → P4-11 → …
- **Task boundary:** `GET /projects/{id}/runs/{run_id}/trace` 返回结构化执行轨迹（Director Intent / Prompt / Resolved Asset Versions / Model Binding / Capability / Approximation / Actual Provider / Actual Model / Redacted Effective Request / Artifact）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §40 Task P4-10

## 依据（03 §40）

- 展示：Director Intent、Prompt、Resolved Asset Versions、Model Binding、Capability、Approximation、Actual Provider、Actual Model、Redacted Effective Request、Artifact。
- 数据来自 NodeRun.input_snapshot（workbench_plan）+ ProviderOperation（actual_provider/model/request_summary）+ Artifact（produced_by_run）。

## Owned paths

- `backend/app/production/trace.py`
- `backend/app/api/v1/workbench.py`
- `backend/tests/unit/test_execution_trace.py`
- `docs/plans/professional-program-v2/task-contracts/P4-10-EXECUTION-TRACE.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-11 ProviderOperation summary 标准化。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `build_execution_trace` 返回全部字段；实际 provider/model 来自 ProviderOperation；effective_request 取 redacted request_summary；无 secret。
- run 不存在 → 404；无 plan snapshot 时字段留空不报错。
- 测试 `test_execution_trace.py` 通过；全量 unit 无回归；ruff/mypy 通过。
