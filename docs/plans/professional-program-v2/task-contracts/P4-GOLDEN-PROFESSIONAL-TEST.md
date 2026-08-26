# Task: §17 Golden Professional Test（Phase 4 收口验收）

## Status

- **State:** IN PROGRESS
- **Task id:** `p4-golden-professional-test`
- **Program order:** P4-01…P4-11（COMPLETED）→ **§17 Golden Professional Test（本任务）** → Phase 5
- **Task boundary:** 真实最小项目垂直切片（1 character / 1 scene / 2 shots；image 模型 + video 模型 A+B；profile video=model B）→ Asset bindings → Keyframe → Formal keyframe → Video → Formal video → Trace；验证 requested==resolved==binding==actual、reference N preserved、manifest/connection/credential revision frozen、page refresh/worker restart/resume/history trace；Negative（Profile X unavailable + Legacy Y 存在 → fail，POST=0）。

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §17
- [`../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md`](../03-DRAMAFORGE_PRO_IMPLEMENTATION_PLAN.md) §42 E2E Gate / §43 阻断条件

## 依据（07 §17 / 03 §42）

- 真实执行链 + 身份链一致 + 负向 fail-closed（Provider POST=0）。
- Director Assistant 全程不存在或关闭。
- 不依赖 Quick / DirectorWorkflow / Budget；不静默丢 Capability；真实 Provider lineage 正确（03 §43）。

## Owned paths

- `scripts/prove_phase4_golden_professional.py`
- `docs/plans/professional-program-v2/task-contracts/P4-GOLDEN-PROFESSIONAL-TEST.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- Phase 5 及以后。
- 修改 03/07 方案正文。

## Verification gate（本任务完成标准）

- 脚本可运行（编译/导入通过；lint 通过）；runbook 记录栈重建 + 迁移 + 真实调用步骤。
- 实跑（栈重建 + Agnes/DeepSeek 真实调用，已授权）后产出证据 JSON：身份链一致、reference 保序、frozen revisions、trace 可读、负向 POST=0。
- 若外部 Provider 不可用或环境未就绪：如实记录 blockers，不伪称通过。
