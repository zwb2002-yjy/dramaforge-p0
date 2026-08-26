# Task: P4-08 Keyframe Formal Selection（Phase 4 Manual Production Alpha）

## Status

- **State:** IN PROGRESS
- **Task id:** `p4-08-keyframe-formal-selection`
- **Program order:** P4-07（COMPLETED）→ **P4-08 Keyframe Formal Selection（本任务）** → P4-09 → …
- **Task boundary:** `POST .../formal-keyframe` 设置 `formal_keyframe_artifact_id`（候选来自 NodeRun+Artifact，不建 Candidate 表）；视频默认用正式关键帧，无正式关键帧不允许用"最新图"兜底。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §38 Task P4-08

## 依据（03 §38）

- Candidate 来自 NodeRun + Artifact（不建 Candidate 表）。
- API `POST /projects/{id}/shots/{sid}/formal-keyframe` 设置 `formal_keyframe_artifact_id`。
- 视频生成默认使用正式关键帧；无正式关键帧时不允许默认拿"最新图"生成视频。

## Owned paths

- `backend/app/production/formal_selection.py`
- `backend/app/api/v1/workbench.py`
- `backend/tests/unit/test_formal_selection.py`
- `docs/plans/professional-program-v2/task-contracts/P4-08-KEYFRAME-FORMAL-SELECTION.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P4-09 视频执行本体、P4-10 trace。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `set_formal_keyframe` 校验 artifact 属于该项目且由该 shot 的 keyframe NodeRun 产生；成功后更新 `Shot.formal_keyframe_artifact_id`（并 bump version）。
- `require_formal_keyframe`：无正式关键帧时抛错（禁止 latest-image 兜底）。
- API `formal-keyframe` 端点可用；测试 `test_formal_selection.py` 通过；全量 unit 无回归；ruff/mypy 通过。
