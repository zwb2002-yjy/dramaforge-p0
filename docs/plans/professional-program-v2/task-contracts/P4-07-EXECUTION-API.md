# Task: P4-07 New Execution API（Phase 4 Manual Production Alpha）

## Status

- **State:** COMPLETE
- **Task id:** `p4-07-execution-api`
- **Program order:** P4-06（COMPLETED）→ **P4-07 New Execution API（本任务）** → P4-08 → …
- **Task boundary:** 新增 `POST /projects/{id}/shots/{sid}/execution-plan`（预览，不调用 Provider）与 `POST .../executions`（执行，`Idempotency-Key` + 服务器重校验 plan fingerprint / expected shot version / accepted approximations）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §37 Task P4-07
- P4-05 `WorkbenchExecutionService`（build_plan / create_and_dispatch）

## 依据（03 §37）

- Preview：`execution-plan` 不调用 Provider。
- Execute：带 `Idempotency-Key`；body 引用 plan fingerprint / expected shot version / accepted approximations；服务器必须重校验。

## Owned paths

- `backend/app/api/v1/workbench.py`
- `backend/app/production/workbench_execution.py`（增加 idempotency key override）
- `backend/tests/unit/test_workbench_api.py`
- `docs/plans/professional-program-v2/task-contracts/P4-07-EXECUTION-API.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-08/09 formal selection、P4-10 trace。
- 真实 Provider 调用（Worker 侧执行）。

## Verification gate（本任务完成标准）

- `execution-plan` 返回冻结计划（fingerprint），不创建 NodeRun。
- `executions`：plan fingerprint 重校验（不匹配 → 4xx）；expected shot version 校验；`Idempotency-Key` 生效（同 key 幂等）；成功后创建 queued NodeRun。
- API 测试 `test_workbench_api.py` 通过；后端全量 unit 无回归；ruff/mypy 通过。
