# V1 G8 — Current-HEAD Release Gate 与 source/image/evidence 绑定

**Task:** `v1-g8-release-gate-20260903`
**Status:** IN PROGRESS（旧运行候选证据不覆盖当前 PR HEAD）
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

## Frozen candidate evidence

- Runtime candidate: `06dd369ea7b1e0f0fa2fd362ee68dc6df16d7357`;
  migration head `20260903_0055`。
- GitHub CI push/PR and Security push/PR：PASS；Release Candidate Gate
  `33733545387`：PASS。
- Release artifact `release-candidate-sha-06dd369ea7b1`，artifact ID
  `9885350784`，uploaded ZIP SHA-256
  `59b7e3813f21f204e779e553a8262af20063139ef7b860116150e1c01037c308`。
- Exact release image digests：backend
  `sha256:75ed47988241921e58904fb5758b0b55ec8b0824c6d2882efea93cc4f0df9ff0`；
  frontend
  `sha256:2273982152d0be0fe2a49a9c0bc0a8ee58916abde4fd79b79249ae09dd4197d9`；
  release manifest digest
  `sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`。
- Non-tag publish/attestation/release steps were skipped by the gate as required;
  no production release was created.
