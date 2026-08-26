# Task: P5-02 shot_experiment Graph Scope（Phase 5 — Experiment / A-B）

## Status

- **State:** IN PROGRESS
- **Task id:** `p5-02-shot-experiment-graph-scope`
- **Program order:** P5-01（COMPLETED）→ **P5-02 shot_experiment Graph Scope（本任务）** → P5-03 → …
- **Task boundary:** GraphService 允许 `scope_type="shot_experiment"`；证明正式图 A 与实验图 B 完全独立（发布 B 不改 A.current_version）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §46 Task P5-02

## 依据（03 §46）

- GraphService 允许 `shot_experiment` scope。
- 测试必须证明：Formal graph version A、Experiment graph version B 完全独立；发布 B 不修改 A.current_version。

## Owned paths

- `backend/app/production/service.py`
- `backend/tests/unit/test_graph_service.py`
- `docs/plans/professional-program-v2/task-contracts/P5-02-SHOT-EXPERIMENT-GRAPH-SCOPE.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P5-03 创建实验 API。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `create_graph` 接受 `scope_type="shot_experiment"`。
- 测试：shot 正式图 A + shot_experiment 图 B 并存；发布 B 后 A.current_version 不变、A 与 B 节点/版本独立。
- 全量 unit 无回归；ruff/mypy 通过。
