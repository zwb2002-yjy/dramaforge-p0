# V1 G6C — Editing→Production Repair 分流

**Task:** `v1-g6c-editing-repair-routing-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G6 OpenCut Director Integration

## Outcome

- 新增 `EditingRepairRoutingService` 与
  `POST .../edit-sessions/{session_id}/director-repair-routing`；
- 服务端用用户指令修复信号或“时间线 Shot 缺少正式视频”的 server fact 判定
  `can_fix_in_timeline`；
- 时间线可修复时返回 Yes（调用方继续走 Editing 建议）；时间线不可修复时
  only 持久化一条 `editing.repair_proposal`（proposal-only），不自动执行
  Repair、不创建 NodeRun/ProviderOperation。

## Owned Paths

- `backend/app/director/editing_repair.py`
- `backend/app/api/v1/editing.py`
- `backend/tests/unit/test_editing_director_suggestion.py`
- `frontend/src/features/editing/api.ts`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/tests/unit/EditingWorkspace.test.tsx`
- `frontend/src/shared/api/generated.ts`
- `docs/plans/professional-program-v2/task-contracts/V1-G6C-EDITING-REPAIR-ROUTING-20260903.md`

## Verification

- backend editing director suggestion suite 20 passed（含 Yes/No/stale/无执行）；
- frontend EditingWorkspace repair routing 用例通过；
- ruff/mypy、frontend lint/typecheck 通过。
