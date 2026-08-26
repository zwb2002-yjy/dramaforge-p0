# Task: P6-02/03 Review UI（Phase 6 — 审片、批注、修复）

## Status

- **State:** IN PROGRESS
- **Task id:** `p6-review-ui`
- **Program order:** Phase 5（COMPLETED）→ **P6-02/03 Review UI（本任务）** → P6-04/05/06 修复 → Phase 6 Gate
- **Task boundary:** P6-01（ReviewAnnotation ORM，image_region x/y/w/h、video_time time_start/end）已由既有 `app/delivery/models.py` + `review.py` API + 迁移 0037/0039 满足（审计确认，不重做）。本任务实现前端 `MediaReviewCanvas.tsx`（图片批注，归一化矩形/点）与 `VideoReviewTimeline.tsx`（视频时间点/范围/文字）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §53/§54/§55

## Owned paths

- `frontend/src/features/review/MediaReviewCanvas.tsx`
- `frontend/src/features/review/VideoReviewTimeline.tsx`
- `frontend/src/features/review/index.ts`
- `frontend/tests/unit/ReviewUI.test.tsx`
- `docs/plans/professional-program-v2/task-contracts/P6-REVIEW-UI.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P6-04/05/06 修复逻辑（下一任务）。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `MediaReviewCanvas`：归一化坐标矩形/点批注可渲染/可交互；坐标输出归一化（0..1）。
- `VideoReviewTimeline`：时间点/时间范围/文字说明渲染。
- vitest 通过；tsc/build/eslint 通过。
