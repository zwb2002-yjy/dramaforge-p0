# V1 G7B — current-HEAD 真实 Provider Golden 与 Final Film

**Task:** `v1-g7b-current-head-golden-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G7/G8 Golden

## Outcome

- `scripts/prove_v1_current_head_golden.py` 创建 Template+AUTO 与 Free+ASSIST
  两个同一 workspace 的项目并导入同一脚本；
- 在 Template+AUTO 项目真实执行 3 个 Shot 的 Agnes keyframe→identity 校验→video，
  每个结果 Mark Formal；
- OpenCut manifest 生成 3 个正式 video clip、15s timeline；
- 创建 EditSession v1 并 export `dramaforge-edit-v1` Final Film manifest；
- 报告记录 ProviderOperation、Artifact、Formal Shot、EditSession、Timeline
  version 与 lineage，无 secret。

## Owned Paths

- `scripts/prove_v1_current_head_golden.py`
- `docs/reviews/GOLDEN-V1-CURRENT-HEAD-20260903.json`
- `docs/plans/professional-program-v2/task-contracts/V1-G7B-CURRENT-HEAD-GOLDEN-20260903.md`

## Verification / Evidence

- evidence：`docs/reviews/GOLDEN-V1-CURRENT-HEAD-20260903.json`
- `ok=true`；`dirty=false`；`source_commit=d46ad15e0886e82c0b07d06c0095dff3f7019783`
- `paid_provider_calls=6`（3× keyframe image + video，全部 succeeded）
- 3 个 Formal Shot；OpenCut timeline 15.000s / 3 video clips；
- EditSession export duration 15.126s。
