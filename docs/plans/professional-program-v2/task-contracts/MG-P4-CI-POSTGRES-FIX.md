# Task: Phase 4 Merge Gate B06 — CI / PostgreSQL integration green on latest HEAD

## Status

- **State:** IN PROGRESS
- **Program order:** … Phase 4 Merge Gate（证据审计已完成）→ **B06 CI/Security green（本任务）** → Owner Gate 确认 → P4 Manual Production Alpha
- **Task boundary:** 只修 Merge Gate B06 所需的 CI 工作流与 PostgreSQL 集成证据链：让 `postgres-integration` 在真实 PG 上可运行且通过、提供 `workflow_dispatch` 手动触发 CI；**不宣布 merge gate 通过**，不进入 P4。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §15 Phase 4 Merge Gate（B06：Latest HEAD CI / Security green）
- [`../gate-reports/PHASE4-MERGE-GATE-AUDIT-REPORT.md`](../gate-reports/PHASE4-MERGE-GATE-AUDIT-REPORT.md)（B01–B05 已关闭；B06 本任务处理）

## 现状事实（代码/迁移/证据确立）

- `alembic upgrade head` 从空 PostgreSQL 失败：迁移 `20260826_0044` 对 `asset_tag_links` 创建基于 `project_id` 的 RLS 策略，但该表只有 `asset_id/tag_id/created_at`（ORM `AssetTagLink` 亦无 `project_id`）。0041–0044 尚未在任何真实 PostgreSQL 上应用（本地栈 DB 停在 `20260826_0040`）。
- CI `postgres-integration` job 未设置 `TEST_PG_ENABLED=1`，集成用例全部 skip，`--fail-on-skip` 使 job 失败。
- `test_catalog_migration_pg.py` 在 `upgrade head` 后断言 `20260826_0040`，已落后于当前 head `20260826_0044`。
- 新 HEAD push 未触发 GitHub Actions（事件未投递），ci.yml 无 `workflow_dispatch`。

## 变更（owned paths 内）

1. `backend/alembic/versions/20260826_0044_phase2_asset_references.py`：`asset_tag_links` 的 RLS 策略改为经 `asset_tags.project_id` 的 EXISTS 子查询（与 `character_references` 既有联结表模式一致），保留策略名 `asset_tag_links_project_scope` 使 downgrade 原样可用。该迁移从未在任何真实数据库应用，原地修正安全。
2. `.github/workflows/ci.yml`：`on:` 增加 `workflow_dispatch`；`postgres-integration` job env 增加 `TEST_PG_ENABLED: "1"`。
3. `backend/tests/integration/test_catalog_migration_pg.py`：head 断言 `20260826_0040` → `20260826_0044`。

## Owned paths

- `.github/workflows/ci.yml`
- `backend/alembic/versions/20260826_0044_phase2_asset_references.py`
- `backend/tests/integration/test_catalog_migration_pg.py`
- `docs/plans/professional-program-v2/task-contracts/MG-P4-CI-POSTGRES-FIX.md`
- `docs/plans/professional-program-v2/gate-reports/PHASE4-MERGE-GATE-AUDIT-REPORT.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- 宣布 Phase 4 Merge Gate 通过（独立 Gate 决策，需 Owner 确认）。
- P4 实现、真实 Provider 付费调用、新功能开发。
- 修改 07 方案正文（仅 Owner 修订可改）。

## Verification gate（本任务完成标准）

- 从空 PostgreSQL 执行 `alembic upgrade head` 成功到 `20260826_0044`。
- `TEST_PG_ENABLED=1` 下 `pytest tests/integration -q -rs --fail-on-skip` 通过（真实 PG，不造假 skip）。
- 后端 unit 全量、ruff/mypy/compileall、`repo_guardrails.py policy`、directory compliance 通过；前端不受影响（CI 复核）。
- `workflow_dispatch` 可手动在最新 HEAD 触发 CI 与 Security；新 HEAD 的 CI/Security 结果如实记录进审计报告（B06 不自行宣布通过）。
