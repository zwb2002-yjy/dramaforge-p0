# V1 G8 — Current-HEAD Release Gate 与 source/image/evidence 绑定

**Task:** `v1-g8-release-gate-20260903`
**Status:** IN PROGRESS
**Goal:** DramaForge V1 统一创作主链 — G8 Release

## Required

- GitHub Actions CI container-gates + Security 全绿（backend/PG/migration/frontend/
  Playwright/LiteLLM）；
- dev push 提交消息含 `[release-candidate]` 时触发 Release Candidate Gate：
  从同一 SHA 构建 exact images、SBOM、release-manifest、smoke 并上传 Artifact；
  非 tag 不发布；
- 更新 `docs/reviews/V1-RELEASE-GATE-REPORT.md` 与 PR #12 body；
- 最终 Owner review/merge（不代批）。

## Owned Paths

- `docs/reviews/V1-RELEASE-GATE-REPORT.md`
- `docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
