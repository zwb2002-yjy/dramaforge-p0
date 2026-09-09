# DramaForge V1 Goal 状态与 Task 索引

**Start:** 2026-09-03
**Goal docs:**

- [`DramaForge_V1_最终创作与导演架构设计方案.md`](DramaForge_V1_最终创作与导演架构设计方案.md)
- [`DramaForge_V1_统一创作主链_Goal执行方案.md`](DramaForge_V1_统一创作主链_Goal执行方案.md)
- [`DramaForge_V1_设计方案_20260907.md`](DramaForge_V1_设计方案_20260907.md)
- [`DramaForge_V1_实施方案_20260907_修订版.md`](DramaForge_V1_实施方案_20260907_修订版.md)

## State

- Status: `GOAL_READY_FOR_OWNER_MERGE`（1–21 项已验证；仅剩 Owner review/approve/merge）
- Runtime candidate: `adf1b9434f59f7dfacf5819d04a77997244e783e`
- Evidence/release candidate: `3677430a75bb92a588a5304508eaff02a278bf03`
- Review PR: [#66](https://github.com/zwb2002-yjy/dramaforge-p0/pull/66)（当前 `dev → main`）
- Gate condition: only the execution plan's GOAL_DONE/GOAL_READY_FOR_OWNER_MERGE states count.

## Task Index

| Task | Contract | Status |
|---|---|---|
| G0 权威基线与架构登记 | task-contracts/V1-G0-AUTHORITY-BASELINE-20260903.md | COMPLETE |
| G1 Story Authoring Proposal Chain | P10-STORY-AUTHORING-PROPOSAL-CHAIN-20260902.md + task-contracts/V1-G1A-STORY-PROPOSAL-BACKEND-20260903.md + task-contracts/V1-G1B-STORY-PROPOSAL-UI-20260903.md | COMPLETE |
| G2 CreativeTemplate 与 ProjectCreativeProfile | task-contracts/V1-G2A-CREATIVE-TEMPLATE-PROFILE-20260903.md | COMPLETE |
| G3 DirectorAutonomy | task-contracts/V1-G3A-DIRECTOR-AUTONOMY-BACKEND-20260903.md + task-contracts/V1-G3B-DIRECTOR-AUTONOMY-UI-20260903.md | COMPLETE |
| G4 Proactive Director Recommendation（Golden 采用证据并入 G7 报告） | task-contracts/V1-G4A-PROACTIVE-RECOMMENDATION-20260903.md + task-contracts/V1-G4B-RECOMMENDATION-UI-20260903.md | COMPLETE* |
| G5 Creation UX 与统一 Canvas | task-contracts/V1-G5A-CREATION-UX-20260903.md | COMPLETE |
| G6 OpenCut Director 主动剪辑建议与 Editing→Repair 分流 | task-contracts/V1-G6A-EDITING-PROACTIVE-20260903.md + task-contracts/V1-G6B-EDITING-PROACTIVE-UI-20260903.md + task-contracts/V1-G6C-EDITING-REPAIR-ROUTING-20260903.md + task-contracts/V1-G6D-EDITING-SUGGESTION-APPLY-20260903.md | COMPLETE |
| G7 统一主链 E2E 与 current-HEAD 双路径真实 Provider Golden | task-contracts/V1-G7A-MAINCHAIN-E2E-20260903.md + task-contracts/V1-G7B-CURRENT-HEAD-GOLDEN-20260903.md + task-contracts/V1-G7D-DUAL-PATH-FINAL-FILM-20260903.md + task-contracts/V1-G7E-FINAL-FILM-ASYNC-TIMELINE-20260903.md + task-contracts/V1-R7-DUAL-PATH-REAL-ACCEPTANCE-20260908.md | COMPLETE |
| G8 Current-HEAD Release Candidate Gate 与 source/image/evidence 绑定 | task-contracts/V1-G8-RELEASE-GATE-20260903.md | COMPLETE — READY FOR OWNER MERGE |

## 2026-09-07 completion revision

| Revision task | Contract | Status |
|---|---|---|
| R0 基线校准与证据重算 | task-contracts/V1-R0-RECONCILIATION-20260907.md | COMPLETE |
| R1 Scene 等待、草稿和阶段操作 | task-contracts/V1-R1-SCENE-WORKFLOW-20260907.md | COMPLETE |
| R2 真实文本导演接通 | task-contracts/V1-R2A-SHOT-TEXT-DIRECTOR-20260907.md + task-contracts/V1-R2B-STORY-TEXT-DIRECTOR-20260907.md + task-contracts/V1-R2C-EDITING-TEXT-DIRECTOR-20260908.md | COMPLETE |
| R3 用户意图、Skills 与模型能力闭环 | task-contracts/V1-R3-EFFECTIVE-CREATIVE-INTENT-20260908.md | COMPLETE |
| R4 有限导演推进与恢复 | task-contracts/V1-R4A-DIRECTOR-TURN-LIFECYCLE-20260908.md + task-contracts/V1-R4B-DIRECTOR-NEXT-ACTION-20260908.md + task-contracts/V1-R4C1-DIRECTOR-USER-DECISIONS-20260908.md + task-contracts/V1-R4C2-DIRECTOR-BUSINESS-CHECKPOINTS-20260908.md + task-contracts/V1-R4C3-DIRECTOR-STATUS-UI-20260908.md | VERIFIED（R4a–R4c3 同候选验证；R7a 已补齐 Editing 拒绝持久化，最终合流 Gate 仍归 R7/R8） |
| R5 生产恢复与重试验收 | task-contracts/V1-R5-RUNTIME-RECOVERY-MATRIX-20260908.md | VERIFIED（含同一真实远端任务重启恢复、零额外 create；root ledger unresolved） |
| R6 Final Film 与最终 SRT | task-contracts/V1-R6-FINAL-FILM-SUBTITLE-DELIVERY-20260908.md | VERIFIED（同候选真 FFmpeg / SRT / PG 与零媒体 rerender；root ledger unresolved） |
| R7 双创作路径与真实用户验收 | task-contracts/V1-R7-DUAL-PATH-REAL-ACCEPTANCE-20260908.md | COMPLETE |
| R8 最终候选与发布准备 | task-contracts/V1-G8-RELEASE-GATE-20260903.md | COMPLETE — READY FOR OWNER MERGE |

## Final completion audit — 2026-09-09

| # | Goal requirement | Authoritative current evidence | Result |
|---:|---|---|---|
| 1 | Legacy hard removal | Canonical/directory gates and full exact-source regression | PASS |
| 2 | Idea → proposal/diff/partial apply → canonical facts | Story/Shot/Editing typed-turn tests plus four persisted real text turns | PASS |
| 3 | Template Start / Free Start create the same Project | Distinct R7 projects share canonical Project/Scene/Shot tables and APIs | PASS |
| 4 | CreativeTemplate initializes only | Template project proceeds through the same runtime; no template runtime exists | PASS |
| 5 | AUTO/ASSIST/MANUAL preserve execution identity | AUTO and ASSIST real paths plus MANUAL no-auto regression | PASS |
| 6 | Proactive performance/action/camera/shot/rhythm/reference recommendation | Director compiler/recommendation gates and real Shot turns | PASS |
| 7 | Whole/partial/reject | Typed decisions and persisted accept/reject/application evidence | PASS |
| 8 | Manual/locked/dirty/stale precedence | Exact-source backend/frontend/E2E negative and stale regressions | PASS |
| 9 | Candidate/Formal/Experiment/Repair boundaries | Nine Formal shots, explicit Review/Repair and negative-boundary evidence | PASS |
| 10 | Unified NodeRun/ProviderOperation/Artifact | Both real projects and all media use the same persisted runtime lineage | PASS |
| 11 | OpenCut/Editing is the formal tail | Both frozen EditSessions render through Final Film delivery | PASS |
| 12 | Partial Editing recommendation adoption | Real Editing turn application plus focused unit/E2E assertions | PASS |
| 13 | Editing-unsuitable issue becomes Repair Proposal | Review/Repair flow and real Agnes Repair operation | PASS |
| 14 | Both start paths share Runtime and EditingAdapter | R7 `distinct_projects_shared_runtime` and dual delivery evidence | PASS |
| 15 | New-project legacy execution call = 0 | Canonical-surface and product-path regression gates | PASS |
| 16 | No fixed shot-count product rule | Real accepted paths complete with five and four Formal shots | PASS |
| 17 | Full quality/security/migration/E2E | Exact `adf1b94` matrix plus CI `34305028424` and Security `34305028341` | PASS |
| 18 | Commit-bound real Provider Golden | `golden-adf1b94.json`, candidate-equivalence proof and final-candidate Repair call | PASS |
| 19 | Real Final Film export | Two playable H.264/AAC films (24.027s and 19.239s) with SRT lineage | PASS |
| 20 | Release evidence/image/source consistency | Release `34305028423`, exact image IDs, bundle digests and OCI/source records | PASS |
| 21 | Owner-reviewable `dev → main` PR | PR [#66](https://github.com/zwb2002-yjy/dramaforge-p0/pull/66) contains full evidence | PASS |

The frozen runtime/evidence set is committed under
`docs/reviews/evidence/v1-r7-current/`. Evidence/release commit `3677430`
changes no backend application, migration, frontend source or dependency input
after runtime candidate `adf1b94`. The final documentation-only commit updates
contracts and review state without changing those frozen identities.

The root lifecycle ledger remains unresolved because preserved user/untracked
inputs make a clean formal registration impossible; no false lifecycle event is
written. This does not weaken the isolated clean-source Gate or PR evidence.
The Agent must not approve or merge PR #66. `GOAL_DONE` is reserved for the
Owner's completed merge followed by an identity/evidence recheck.
