# Task: Phase 8 — 2D/3D 导演台（P8-01/02/03/04/07 + Gate）

## Status

- **State:** COMPLETE
- **Task id:** `p8-director-board`
- **Program order:** Phase 7（COMPLETED）→ **Phase 8 导演台（本任务）** → Phase 9
- **Task boundary:** P8-01 2D SVG 导演画布（角色/摄影机/场景对象/朝向/动作路径/视线/构图边界 → Scene.design_state.blocking_2d + Shot.director_state）；P8-02/03 Camera/Pose/Gaze 控件类型；P8-04 DirectorControlPackage（composition/camera/pose/gaze/blocking → WorkbenchExecutionPlan，exact/approximate）；P8-07 SceneAssembler（语义 SceneLayoutSpec → 确定性坐标，禁止 LLM 直接生成最终坐标）；Phase 8 Gate（多人复杂场景 6 项）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §71-79

## Owned paths

- `backend/app/director/control_package.py`
- `backend/app/director/scene_assembler.py`
- `backend/app/api/v1/director_board.py`
- `frontend/src/features/director/DirectorBoard2D.tsx`
- `frontend/tests/unit/DirectorBoard2D.test.tsx`
- `backend/tests/unit/test_phase8_gate.py`
- `docs/plans/professional-program-v2/task-contracts/P8-DIRECTOR-BOARD.md`
- `docs/开发执行检查点.md`

## Verification gate（本任务完成标准）

- DirectorControlPackage 语义输出 + exact/approximate；接入 plan preview。
- SceneAssembler 确定性生成坐标。
- 2D SVG 画布可渲染/写 blocking_2d + director_state。
- Phase 8 Gate 6 项证明（2D 可摆、可切 3D 状态一致（数据结构）、转 ControlPackage、不支持控制 warning、可跳过直接生成）。
- 全量 unit + vitest 无回归；ruff/mypy、tsc/build 通过。
