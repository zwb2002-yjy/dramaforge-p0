# V1 G3A — DirectorAutonomy 后端策略与切换

**Task:** `v1-g3a-director-autonomy-backend-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G3 DirectorAutonomy

## Outcome

- `DirectorAutonomyPolicy` 集中定义 AUTO/ASSIST/MANUAL 行为（主动分析、推荐显示、
  proposal 自动生成、高级参数密度、付费确认）；
- `PATCH /projects/{project_id}/creative-profile` 支持乐观版本切换
  `director_autonomy`；
- Media/Model/Runtime 代码不读取 autonomy；同一 Shot/输入下 autonomy 不改变
  resolution 与执行身份。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G3A-DIRECTOR-AUTONOMY-BACKEND-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `backend/app/api/v1/projects.py`
- `backend/app/director/autonomy_policy.py`
- `backend/tests/unit/test_director_autonomy.py`
- `frontend/src/shared/api/generated.ts`

## Success Criteria

1. 三档 policy 行为矩阵与设计一致；
2. PATCH stale version fail closed；
3. runtime/model code 不引用 autonomy；
4. focused + full backend unit 通过；
5. OpenAPI 同步。

## Evidence

- commit SHA：提交后回填；
- focused：`test_director_autonomy.py` 4 passed；
- full backend unit：863 passed；
- ruff/mypy/OpenAPI 同步通过。
