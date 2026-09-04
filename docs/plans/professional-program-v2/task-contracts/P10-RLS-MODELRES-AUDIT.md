# Task: Phase 10 — RLS + Model Resolution Audit（P10-05 + 07 §23）

## Status

- **State:** COMPLETE
- **Task id:** `p10-rls-modelres-audit`
- **Program order:** P10-03/04（COMPLETED）→ **本任务（P10-05 RLS + 07 §23 Model Resolution）** → Golden / E2E / V1 Gate
- **Task boundary:** P10-05 RLS Audit（workspace state / asset version / tag / binding / experiment / annotation / director assistant / proposal：tenant isolation + FORCE RLS + cross-project negative test）；07 §23 Final Model Resolution Audit（Professional 正式路径不存在绕过 ExecutionModelResolver 的真实媒体调用；worker 消费冻结 resolution）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §92
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §23

## Owned paths

- `backend/tests/integration/test_phase10_rls_modelres_audit_pg.py`
- `docs/plans/professional-program-v2/task-contracts/P10-RLS-MODELRES-AUDIT.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- 真实 PG 集成测试：
  - Schema 审计：P10-05 列出的全部表均 `FORCE ROW LEVEL SECURITY` 且至少 1 条 policy。
  - Cross-project 负向：project B 的 rows 在 project A 上下文下全部不可见（workspace state/asset version/binding/experiment/annotation/director assistant/proposal/edit session 等）。
  - Model Resolution：`WorkbenchExecutionService.build_plan` 经 `ExecutionModelResolver` 得到 RESOLVED 冻结 resolution；`create_and_dispatch` 把冻结 plan 写入 NodeRun.input_snapshot（worker 消费冻结 resolution，无直连 provider）。
- 全量 unit / integration（TEST_PG_ENABLED=1）通过；ruff/mypy 通过。
