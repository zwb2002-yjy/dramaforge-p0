# Task: P4-06 Workbench Graph（Phase 4 Manual Production Alpha）

## Status

- **State:** COMPLETE
- **Task id:** `p4-06-workbench-graph`
- **Program order:** P4-05（COMPLETED）→ **P4-06 Workbench Graph（本任务）** → P4-07 → …
- **Task boundary:** 确认/补测 GraphService 的 `scope_type=shot` 路径（沿用既有 Shot Pipeline，不重写 `shot_pipeline.py`）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §36 Task P4-06
- 现有 `app/production/service.py`（GraphService）、`app/execution/shot_pipeline.py`

## 依据（03 §36）

- 扩 GraphService，此阶段只需 `scope_type = shot`。
- 继续使用现有 Shot Pipeline；不重写 `shot_pipeline.py`，除非 Node contract 不足以执行真实业务。
- P4-05 `create_and_dispatch` 已用 GraphService（scope_type=shot + SHOT_PIPELINE_TEMPLATE_KEY）；本任务补齐显式 shot-pipeline 图往返测试。

## Owned paths

- `backend/tests/unit/test_graph_service.py`
- `docs/plans/professional-program-v2/task-contracts/P4-06-WORKBENCH-GRAPH.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- 重写 shot_pipeline.py / Node contract。
- P4-07 API / 真实模型执行。

## Verification gate（本任务完成标准）

- 新增 shot-scope 图往返测试：`create_graph(scope_type="shot", template_key=SHOT_PIPELINE_TEMPLATE_KEY, definition=shot_pipeline_definition(...))` → materialize → publish → nodes 含 keyframe/video；非法 scope_type 拒绝。
- `test_graph_service.py` 全绿；后端全量 unit 无回归；ruff/mypy 通过。
