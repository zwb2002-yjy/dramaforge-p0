# Task: P4-09 Video Execution（Phase 4 Manual Production Alpha）

## Status

- **State:** IN PROGRESS
- **Task id:** `p4-09-video-execution`
- **Program order:** P4-08（COMPLETED）→ **P4-09 Video Execution（本任务）** → P4-10 → …
- **Task boundary:** 视频执行计划强制携带正式关键帧（无正式关键帧 fail-closed，禁止 latest-image 兜底）；`POST .../formal-video` 设置 `formal_video_artifact_id`。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §39 Task P4-09（含 Video Formal Selection）

## 依据（03 §38/§39）

- 视频标准链：formal keyframe + video prompt + references + director state + visual standard → video execution plan → video NodeRun。
- 视频默认使用正式关键帧；无正式关键帧不允许"最新图"兜底。
- `POST /projects/{id}/shots/{sid}/formal-video` 设置 `formal_video_artifact_id`。

## Owned paths

- `backend/app/production/workbench_execution.py`
- `backend/app/production/formal_selection.py`
- `backend/app/api/v1/workbench.py`
- `backend/tests/unit/test_workbench_execution.py`
- `backend/tests/unit/test_formal_selection.py`
- `docs/plans/professional-program-v2/task-contracts/P4-09-VIDEO-EXECUTION.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-10 trace、P4-11 ProviderOperation summary。
- 真实 Provider 调用（Worker 侧执行）。

## Verification gate（本任务完成标准）

- `stage="video"` 的 build_plan：无正式关键帧 → fail-closed；有 → 计划引用注入 first_frame（正式关键帧）。
- `set_formal_video`：校验 artifact 由该项目该 shot 的 video NodeRun 产生并设置 `formal_video_artifact_id`；API `formal-video` 可用。
- 既有 P4-05 视频用例更新为带正式关键帧；新增视频 formal / 强制关键帧测试；全量 unit 无回归；ruff/mypy 通过。
