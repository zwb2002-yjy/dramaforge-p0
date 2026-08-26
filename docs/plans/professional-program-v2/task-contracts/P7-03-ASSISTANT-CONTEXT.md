# Task: P7-03 Assistant Context Builder（Phase 7 — 导演智能体 Copilot）

## Status

- **State:** IN PROGRESS
- **Task id:** `p7-03-assistant-context`
- **Program order:** P7-02（COMPLETED）→ **P7-03 Assistant Context Builder（本任务）** → P7-04 → …
- **Task boundary:** `backend/app/director/assistant_context.py`：每轮重读 Project/Visual Standard/Scene/Shot/Formal Assets/References/Current Model Capability/Current Experiments/Open Annotations + recent messages + current message；DB facts 优先。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §63 Task P7-03

## Owned paths

- `backend/app/director/assistant_context.py`
- `backend/tests/unit/test_assistant_context.py`
- `docs/plans/professional-program-v2/task-contracts/P7-03-ASSISTANT-CONTEXT.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- 上下文含全部要求的 DB 事实 + recent messages + current message；Scene 归属经 Episode 校验；`context_priority=database_facts`。
- 测试通过；全量 unit 无回归；ruff/mypy 通过。
