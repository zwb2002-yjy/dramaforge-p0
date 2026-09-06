# V1 G4A — Proactive Director Recommendation（Backend）

**Task:** `v1-g4a-proactive-recommendation-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G4 Proactive Director Recommendation

## Outcome

- `POST /projects/{id}/shots/{shot_id}/recommendation` 无需 user_instruction；
- 服务端读取 Shot/Scene 事实与设计状态，返回结构化 DirectorRecommendation：
  scope/category/current_state/suggested_change/reason/expected_effect/risk/
  affected_facts/base_versions/typed_operations；
- typed_operations 递归禁止 Provider/Runtime/SQL/Artifact 字段；
- stale expected_shot_version fail closed，不修改 Shot。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G4A-PROACTIVE-RECOMMENDATION-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `backend/app/api/v1/director.py`
- `backend/app/director/recommendation.py`
- `backend/tests/unit/test_director_recommendation.py`
- `frontend/src/shared/api/generated.ts`

## Success Criteria

1. 无 user_instruction 生成有效推荐；
2. 推荐含 reason/effect/risk/affected facts；
3. stale fail closed；
4. 非法字段 fail closed；
5. full backend unit / ruff / mypy / OpenAPI 同步。

## Evidence

- focused：`test_director_recommendation.py` 5 passed；
- full backend unit：868 passed；
- ruff/mypy/OpenAPI 同步通过。
