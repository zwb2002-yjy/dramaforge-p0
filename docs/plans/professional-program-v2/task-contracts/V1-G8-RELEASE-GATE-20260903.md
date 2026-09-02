# V1 G8 — Current-HEAD Release Gate 与 source/image/evidence 绑定

**Task:** `v1-g8-release-gate-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G8 Release

## Required

- GitHub Actions CI container-gates + Security 全绿（backend/PG/migration/frontend/
  Playwright/LiteLLM）；
- Release workflow（exact source images + SBOM + release-manifest）记录
  source SHA、image digest、migration head；
- 更新 `docs/reviews/V1-RELEASE-GATE-REPORT.md` 与 PR #12 body；
- 最终 Owner review/merge（不代批）。

## Owned Paths

- `docs/reviews/V1-RELEASE-GATE-REPORT.md`
- `docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
