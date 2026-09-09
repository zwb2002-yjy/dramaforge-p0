# V1 G8 — Current-HEAD Release Gate 与 source/image/evidence 绑定

**Task:** `v1-g8-release-gate-20260903`
**Status:** COMPLETE — `GOAL_READY_FOR_OWNER_MERGE`
**Goal:** DramaForge V1 统一创作主链 — G8 Release

## Required

- GitHub Actions CI container-gates + Security 全绿（backend/PG/migration/frontend/
  Playwright/LiteLLM）；
- `dev` push 提交消息含 `[release-candidate]` 时触发 Release Candidate Gate：
  从同一 SHA 构建 exact images、SBOM、release-manifest、smoke 并上传 Artifact；
  非 tag 不发布；
- 更新 `docs/reviews/V1-RELEASE-GATE-REPORT.md` 与当前 `dev → main` PR body；
- 最终 Owner review/merge（不代批）。

## Owned Paths

- `docs/reviews/V1-RELEASE-GATE-REPORT.md`
- `docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`

## Final frozen candidate — 2026-09-09

- Runtime candidate:
  `adf1b9434f59f7dfacf5819d04a77997244e783e`; migration head
  `20260908_0060`.
- Evidence/release candidate:
  `3677430a75bb92a588a5304508eaff02a278bf03`. Its diff after `adf1b94`
  changes no backend application, migration, frontend source or dependency
  input; it contains acceptance tooling/tests, the redacted evidence set and
  the workflow correction that uploads that evidence on candidate pushes.
- The final documentation commit is review-only and therefore does not replace
  the frozen runtime or release identity. PR #66 tracks the current `dev` head.

## Exact-source verification

- Clean exact runtime source `adf1b94` passed directory/canonical checks, Ruff,
  MyPy on 243 source files, 1008 backend unit tests, 45 PostgreSQL/real-FFmpeg
  integration tests, migration/drift/OpenAPI gates, frontend API/format/lint/
  type/build, 152 frontend unit tests, 19 Playwright E2E tests and five pinned
  LiteLLM integration tests.
- The real non-mock browser acceptance passed on the exact runtime stack at
  entry port 8080 with zero failed API responses, page errors or console errors.
- Evidence candidate `3677430` passed CI run `34305028424` and Security run
  `34305028341`.
- Release run `34305028423` passed source verification, the exact container
  quality gate, migration-head resolution, exact image build, Compose smoke,
  source/image SBOM generation, release manifest, online/offline bundle and
  checksum creation, plus both Artifact uploads.

## Release identity and downloadable artifacts

- Exact release backend image ID:
  `sha256:9ba7dce2fc65c0c1768796a7212e504f8ae19399dbd9133800bdb1ca6a05205f`.
- Exact release frontend image ID:
  `sha256:4b8d77a56b4841d6d4fe6c48b862606d5e54ddd386624f4ca3f87d4f399642b2`.
- Release bundle `release-candidate-sha-3677430a75bb`: artifact ID
  `10086614647`, 1,101,669,773 bytes, upload digest
  `sha256:9b0610e8e4fdb35a2a4f1a92f6797ad61d2d9d0fdb8596e263f65e9b98a423f3`.
- Golden/Final Film bundle
  `v1-r7-current-golden-3677430a75bb92a588a5304508eaff02a278bf03`:
  artifact ID `10086615067`, 8,368,303 bytes, upload digest
  `sha256:81cb73c5c817a9d2f2671b34a92696525ee9da7ff96af235d9bfea2a9fdbc88c`.
- This was a non-tag candidate push. Registry publish, provenance attestation
  and GitHub Release creation were skipped as required; no production release
  was created.

## Review and remaining boundary

The committed redacted evidence is under
`docs/reviews/evidence/v1-r7-current/`. PR #66 contains the complete review
summary and links the frozen runtime, CI/Security/Release runs, exact image IDs,
real Provider lineage and both Final Films. Historical PR #12 was already
merged at an older head and is not reused as current evidence.

The root lifecycle ledger still cannot be legitimately closed while preserved
user/untracked inputs are present, so no false `COMPLETED` or `MERGED` ledger
event is written. This does not alter the clean isolated candidate, committed
evidence, GitHub gates or PR diff. The only release action remaining is the
Owner's independent review/approval/merge of PR #66; the Agent must not perform
it.
