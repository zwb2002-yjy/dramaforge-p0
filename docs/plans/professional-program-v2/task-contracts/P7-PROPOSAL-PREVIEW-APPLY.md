# Task: P7-06/07 Proposal Preview UI + Partial Apply（Phase 7）

## Status

- **State:** COMPLETE
- **Task id:** `p7-proposal-preview-apply`
- **Program order:** P7-04/05（COMPLETED）→ **P7-06/07 Proposal Preview UI + Partial Apply（本任务）** → P7-08 → …
- **Task boundary:** `ProposalPreview.tsx`/`ProposalItem.tsx`（每项显示 建议/原因/收益/代价/风险/影响范围 + 接受/拒绝）；后端 partial apply 只执行 Accepted 项。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §66/§67

## Owned paths

- `frontend/src/features/director/ProposalPreview.tsx`
- `frontend/src/features/director/ProposalItem.tsx`
- `frontend/tests/unit/ProposalPreview.test.tsx`
- `backend/app/director/proposal_service.py`
- `backend/tests/unit/test_proposal_service.py`
- `docs/plans/professional-program-v2/task-contracts/P7-PROPOSAL-PREVIEW-APPLY.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- ProposalItem 显示 建议/原因/收益/代价/风险/影响范围 + 接受/拒绝；ProposalPreview 逐项渲染。
- partial apply：只执行 Accepted 项（Registry 应用 + 状态标记），Rejected 不执行。
- 测试通过；全量 unit 无回归；ruff/mypy、tsc/build/eslint 通过。
