# Task: Phase 10 — Golden Real-Provider Run（§95 验证节收口）

## Status

- **State:** COMPLETE
- **Task id:** `p10-golden-real-run`
- **Program order:** V1 Release Gate（COMPLETED，Golden 项标为环境门控）→ **本任务（真实 provider 实跑 + 证据）**
- **Task boundary:** 重建 dev 栈到当前代码（后端镜像 + 迁移 dev 库 0040→0049），运行真实 Agnes 关键帧/视频 golden 实跑，修补 `prove_phase4_golden_professional.py` 的过时认证/轮询/场景创建契约，证据写入 `docs/reviews/`，回填 V1 Gate 报告。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §95
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §23

## Owned paths

- `scripts/prove_phase4_golden_professional.py`
- `docs/reviews/GOLDEN-REAL-PROVIDER-RUN-2026-08-27.json`
- `docs/reviews/V1-RELEASE-GATE-REPORT.md`
- `docs/plans/professional-program-v2/task-contracts/P10-GOLDEN-REAL-RUN.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- dev 栈后端重建 + 迁移到 `20260827_0049`，新端点可访问。
- 真实 golden 实跑 `scripts/prove_professional_agnes_golden.py` 返回 `ok=true`、`paid_provider_calls >= 1`，证据 JSON 无 secret 并保存到 `docs/reviews/`。
- `scripts/prove_phase4_golden_professional.py` 认证/轮询/ops/场景创建契约更新到当前 API（cookie+CSRF+X-Workspace-Id、run trace 轮询、snapshot ops、scripts/import）；其单节点分发依赖上游 run 的限制如实记录。
- V1 Gate 报告回填实跑结果；ruff/mypy 通过。
