# Task: Phase 10 — V1 Release Gate（03 §95）

## Status

- **State:** COMPLETE
- **Task id:** `p10-v1-release-gate`
- **Program order:** P10-07 V1 E2E（COMPLETED）→ **本任务（V1 Release Gate）** → 完成（Golden 真实 provider 运行属环境门控项，需重建 compose + 真实 Agnes/DeepSeek，单独记录）
- **Task boundary:** 全矩阵验证（§95 验证节）并产出 `docs/reviews/V1-RELEASE-GATE-REPORT.md`，逐条映射 §95 架构/手动生产/资产/模型/实验/审片/导演智能体/导演台/剪辑/验证 到证据（各阶段 Gate 测试、audit 测试、提交、全量套件结果）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §95
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §23

## Owned paths

- `docs/reviews/V1-RELEASE-GATE-REPORT.md`
- `docs/plans/professional-program-v2/task-contracts/P10-V1-RELEASE-GATE.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- 重新跑全矩阵并记录结果：Backend static（ruff/mypy）、Backend unit、PostgreSQL integration（TEST_PG_ENABLED=1）、Frontend lint/type/test/build、Playwright 全量。
- 报告逐条覆盖 §95 全部子项；「Golden real provider run」如实标记为环境门控（命令与前置条件写明），不伪称通过。
- 报告写入 `docs/reviews/V1-RELEASE-GATE-REPORT.md` 并提交。
