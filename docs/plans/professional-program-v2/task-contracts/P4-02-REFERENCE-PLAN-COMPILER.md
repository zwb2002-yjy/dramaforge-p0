# Task: P4-02 ReferencePlanCompiler（Phase 4 Manual Production Alpha）

## Status

- **State:** IN PROGRESS
- **Task id:** `p4-02-reference-plan-compiler`
- **Program order:** P4-01（COMPLETED）→ **P4-02 ReferencePlanCompiler（本任务）** → P4-03/MS8 → …
- **Task boundary:** 只实现业务 purpose → ModelManifest input slot 的翻译（exact/approximate/unsupported）；不接 API、不改 Provider 调用。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §16 P4-02
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §32 Task P4-02
- P4-01 合同与 `execution_plan.py`（`PlannedReference` / `CapabilityGap`）

## 依据（03 §32）

- 新增 `backend/app/production/reference_intents.py`。
- 负责 identity / clothing / action / camera_language / ... → ModelManifest input slots 翻译。
- 必须区分 exact / approximate / unsupported。
- 禁止：当前模型不支持却静默丢引用。
- Unit tests `test_reference_plan_compiler.py` 覆盖：generic image ref、first/last、multi reference、unsupported video reference、purpose approximate、ref count exceed、mutually exclusive。

## Owned paths

- `backend/app/production/reference_intents.py`
- `backend/tests/unit/test_reference_plan_compiler.py`
- `docs/plans/professional-program-v2/task-contracts/P4-02-REFERENCE-PLAN-COMPILER.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-05 WorkbenchExecutionService / API。
- 任何 Provider 调用或真实模型执行。
- 修改 07/03 方案正文。

## Verification gate（本任务完成标准）

- `reference_intents.py` 纯函数/纯 Pydantic，无 ORM/IO。
- unsupported 引用不静默丢弃：保留在输出并上升为 `CapabilityGap`（fatal）。
- approximate 引用需显式 `accept_approximations` 才接受。
- cardinality（slot maximum）与 mutually-exclusive group 生效。
- unit `test_reference_plan_compiler.py`（7 用例）通过；后端全量 unit 无回归；ruff/mypy/guardrails 通过。
