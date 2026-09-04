# V1 G2A — CreativeTemplate 与 ProjectCreativeProfile

**Task:** `v1-g2a-creative-template-profile-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G2 CreativeTemplate 与 ProjectCreativeProfile

## Outcome

- 新增代码版本化 CreativeTemplate Registry，内置三个模板：
  双人对白反转、单人情绪独白、自由短剧基础；
- 新增 `project_creative_profiles` 单项目 profile；
- `POST /projects` 支持 `start_type=TEMPLATE|FREE`；TEMPLATE 必须提供有效
  template key/version，FREE 只写最小 profile；
- Template 实例化只创建 Profile/默认风格与技能引用，不创建
  Scene/Shot/ExecutionPlan/NodeRun/ProviderOperation；
- Profile 可追踪 template key/version/contract_hash/strategy_snapshot。

## Owned Paths

- `docs/plans/professional-program-v2/task-contracts/V1-G2A-CREATIVE-TEMPLATE-PROFILE-20260903.md`
- `backend/alembic/versions/20260903_0052_creative_profiles.py`
- `backend/app/access/models.py`
- `backend/app/access/projects.py`
- `backend/app/api/v1/projects.py`
- `backend/app/director/creative_capabilities/creative_templates.py`
- `backend/tests/unit/test_creative_template_profile.py`

## Explicitly Out of Scope

- DirectorAutonomy 行为策略实现（G3）；
- 创建页 UI（G5）；
- Template 升级/后台；
- 任何固定 Shot 数或 Runtime。

## Success Criteria

1. Template 创建只产生 1 Project + 1 Profile；
2. Free 创建不套用 Template；
3. TEMPLATE 无效 key fail closed；
4. Apply 零 Provider/NodeRun/ProductionGraph；
5. full backend/migration gate 通过。

## Evidence

- commit SHA：提交后回填；
- focused：`test_creative_template_profile.py` 5 passed；
- full backend unit：859 passed；
- ruff/mypy：通过；
- OpenAPI/generated client 已同步。
