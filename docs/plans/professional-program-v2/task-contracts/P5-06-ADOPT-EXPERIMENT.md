# Task: P5-06 Adopt Experiment API（Phase 5 — Experiment / A-B）

## Status

- **State:** COMPLETE
- **Task id:** `p5-06-adopt-experiment`
- **Program order:** P5-05（COMPLETED）→ **P5-06 Adopt Experiment API（本任务）** → Phase 5 Gate
- **Task boundary:** `POST /projects/{id}/experiments/{id}/adopt`，支持 current_result_only / keyframe_only / keyframe_and_rerun_video / design_only / full_shot；keyframe_only 场景保留旧正式视频并暴露"仍基于旧关键帧"状态。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §50 Task P5-06

## 依据（03 §50）

- API `POST /projects/{id}/experiments/{id}/adopt`。
- scope：current_result_only、keyframe_only、keyframe_and_rerun_video、design_only、full_shot。
- Key E2E：keyframe only → 正式 keyframe B、video A；UI 明确"当前正式视频仍基于旧关键帧"。

## Owned paths

- `backend/app/production/experiment_service.py`
- `backend/app/api/v1/experiments.py`
- `backend/tests/unit/test_experiment_service.py`
- `docs/plans/professional-program-v2/task-contracts/P5-06-ADOPT-EXPERIMENT.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- Phase 5 Gate 判定（后续任务/验收）。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- 各 scope 采纳语义正确：keyframe_only 只更新正式 keyframe（保留旧 video）；current_result_only/full_shot 更新 keyframe+video；design_only 只复制设计输入；keyframe_and_rerun_video 清空正式 video 待重跑。
- keyframe_only 后暴露 `formal_video_stale_keyframe` 状态。
- 测试通过；全量 unit 无回归；ruff/mypy 通过。
