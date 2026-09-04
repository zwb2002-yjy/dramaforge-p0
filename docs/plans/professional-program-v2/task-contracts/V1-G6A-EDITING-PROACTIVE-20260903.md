# V1 G6A — OpenCut Director 主动剪辑建议

**Task:** `v1-g6a-editing-proactive-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G6 OpenCut Director Integration

## Outcome

- EditSession 新增无 user_instruction 的主动剪辑建议；
- 复用现有 typed DirectorProposal / EditingAdapter，不重写 OpenCut；
- stale fail closed、production lineage 只读、不创建 NodeRun。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G6A-EDITING-PROACTIVE-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `backend/app/director/editing_suggestion.py`
- `backend/app/api/v1/editing.py`
- `backend/tests/unit/test_editing_director_suggestion.py`
- `frontend/src/shared/api/generated.ts`

## Success Criteria

1. 主动建议端点无需 instruction；
2. 无 Provider/NodeRun/lineage 写；
3. full unit / OpenAPI 同步。

## Evidence

- focused：16 passed；
- full backend unit：870 passed；
- OpenAPI/generated client 同步。
