# Task: Phase 10 — Golden Professional Project（P10-06）

## Status

- **State:** COMPLETE
- **Task id:** `p10-golden-project`
- **Program order:** P10-05 RLS（COMPLETED）→ **本任务（P10-06 Golden Project）** → P10-07 V1 E2E → V1 Release Gate
- **Task boundary:** 建立一套稳定真实验收项目（03 §93）：脚本 / 2+ Scene / 同一主角 / 2+角色参考角度 / 场景资产 / 多 Shot / 关键帧 / 视频 / 实验 / 审片修复 / Director Proposal / 2D 导演台 / 剪辑 / 导出。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §93

## Owned paths

- `backend/app/production/golden_project.py`
- `backend/tests/integration/test_phase10_golden_project_pg.py`
- `scripts/seed_acceptance_fixture.py`
- `docs/plans/professional-program-v2/task-contracts/P10-GOLDEN-PROJECT.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- `seed_golden_project` 生成确定性 Golden Project（脚本导入、2+ 场景、同一主角、2+ 角色参考角度、场景资产、4 Shot、formal keyframe+video、实验分支、审片 open+resolved 批注与 repair plan、Director Proposal+item、Scene.design_state.blocking_2d + Shot.director_state、EditSession、Export）。
- 真实 PG 集成测试断言全部 P10-06 元素存在且可读。
- `scripts/seed_acceptance_fixture.py` CLI 可对开发库种子化并输出项目 id/计数（无真实 provider 调用、无 secret）。
- 全量 unit / integration（TEST_PG_ENABLED=1）通过；ruff/mypy 通过。
