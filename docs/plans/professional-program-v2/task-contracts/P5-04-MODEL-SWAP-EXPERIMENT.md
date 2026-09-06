# Task: P5-04 Model Swap Experiment（Phase 5 — Experiment / A-B）

## Status

- **State:** COMPLETE
- **Task id:** `p5-04-model-swap-experiment`
- **Program order:** P5-03（COMPLETED）→ **P5-04 Model Swap Experiment（本任务）** → P5-05 → …
- **Task boundary:** "换模型验证" = create ShotExperiment + model_overrides；保留 semantic prompt / asset refs / common controls；丢弃 model A native options；按 Model B Manifest 重编译。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §48 Task P5-04

## 依据（03 §48）

- 换模型验证：create ShotExperiment + model_overrides。
- 参数迁移：保留 semantic prompt、asset refs、common controls；丢弃 model A native options；按 Model B Manifest 重新编译。

## Owned paths

- `backend/app/production/experiment_service.py`
- `backend/tests/unit/test_experiment_service.py`
- `docs/plans/professional-program-v2/task-contracts/P5-04-MODEL-SWAP-EXPERIMENT.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- P5-05 compare UI、P5-06 adopt。
- 真实 Provider 调用。

## Verification gate（本任务完成标准）

- `recompile_controls_for_model`（纯函数）：保留 common_controls 中 B manifest 声明的语义控制；丢弃 B 未声明的 native options；unsupported 控制显式暴露；reference 用 P4-02 按 B 编译。
- `create_model_swap_experiment`：对带 model_override 的 ShotExperiment 写入重编译后的 common_controls（丢弃 A native options）。
- 测试通过；全量 unit 无回归；ruff/mypy 通过。
