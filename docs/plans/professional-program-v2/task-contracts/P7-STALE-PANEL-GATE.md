# Task: P7-08/09 + Phase 7 Gate（导演智能体 Copilot 收口）

## Status

- **State:** IN PROGRESS
- **Task id:** `p7-stale-panel-gate`
- **Program order:** P7-06/07（COMPLETED）→ **P7-08/09 + Phase 7 Gate（本任务）** → Phase 8
- **Task boundary:** P7-08 每 item 带 expected_target_version，手动改版后旧 proposal stale；P7-09 导演面板关闭语义（已提交 run 继续、Agent 不主动提新建议、未确认 proposal 不执行）；Phase 7 Gate（§70 E2E：接受 2 项拒绝 1 项 → 只改 2 项、model 不变、version 正确；手动改版后旧建议 stale）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §68/§69/§70

## Owned paths

- `backend/app/director/proposal_service.py`
- `backend/tests/unit/test_proposal_stale_panel.py`
- `docs/plans/professional-program-v2/task-contracts/P7-STALE-PANEL-GATE.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- `mark_proposals_stale_for_shot`：手动改版后 pending item → stale。
- Phase 7 Gate 测试：接受低机位+补参考、拒绝换模型 → 只改 2 项、model 不变、version 正确；手动改版后旧建议 stale 拒绝。
- 全量 unit 无回归；ruff/mypy 通过。
