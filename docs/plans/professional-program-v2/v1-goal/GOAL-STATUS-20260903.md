# DramaForge V1 Goal 状态与 Task 索引

**Start:** 2026-09-03
**Goal docs:**

- [`DramaForge_V1_最终创作与导演架构设计方案.md`](DramaForge_V1_最终创作与导演架构设计方案.md)
- [`DramaForge_V1_统一创作主链_Goal执行方案.md`](DramaForge_V1_统一创作主链_Goal执行方案.md)
- [`DramaForge_V1_设计方案_20260907.md`](DramaForge_V1_设计方案_20260907.md)
- [`DramaForge_V1_实施方案_20260907_修订版.md`](DramaForge_V1_实施方案_20260907_修订版.md)

## State

- Status: GOAL_IN_PROGRESS（R0–R4 已闭环；R5–R8 仍需实现与同候选验收）
- Baseline: dev@67bbde25f6e9739ff2259f678394c63b2c37284a
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
| G7 统一主链 E2E 与 current-HEAD 双路径真实 Provider Golden | task-contracts/V1-G7A-MAINCHAIN-E2E-20260903.md + task-contracts/V1-G7B-CURRENT-HEAD-GOLDEN-20260903.md + task-contracts/V1-G7D-DUAL-PATH-FINAL-FILM-20260903.md + task-contracts/V1-G7E-FINAL-FILM-ASYNC-TIMELINE-20260903.md | IN PROGRESS |
| G8 Current-HEAD Release Candidate Gate 与 source/image/evidence 绑定 | task-contracts/V1-G8-RELEASE-GATE-20260903.md | IN PROGRESS |

## 2026-09-07 completion revision

| Revision task | Contract | Status |
|---|---|---|
| R0 基线校准与证据重算 | task-contracts/V1-R0-RECONCILIATION-20260907.md | COMPLETE |
| R1 Scene 等待、草稿和阶段操作 | task-contracts/V1-R1-SCENE-WORKFLOW-20260907.md | COMPLETE |
| R2 真实文本导演接通 | task-contracts/V1-R2A-SHOT-TEXT-DIRECTOR-20260907.md + task-contracts/V1-R2B-STORY-TEXT-DIRECTOR-20260907.md + task-contracts/V1-R2C-EDITING-TEXT-DIRECTOR-20260908.md | COMPLETE |
| R3 用户意图、Skills 与模型能力闭环 | task-contracts/V1-R3-EFFECTIVE-CREATIVE-INTENT-20260908.md | COMPLETE |
| R4 有限导演推进与恢复 | task-contracts/V1-R4A-DIRECTOR-TURN-LIFECYCLE-20260908.md + task-contracts/V1-R4B-DIRECTOR-NEXT-ACTION-20260908.md + task-contracts/V1-R4C1-DIRECTOR-USER-DECISIONS-20260908.md + task-contracts/V1-R4C2-DIRECTOR-BUSINESS-CHECKPOINTS-20260908.md + task-contracts/V1-R4C3-DIRECTOR-STATUS-UI-20260908.md | COMPLETE（R4a–R4c3 已通过同候选验证；ledger unresolved 限制已如实记录） |
| R5 生产恢复与重试验收 | task-contracts/V1-R5-RUNTIME-RECOVERY-MATRIX-20260908.md | VERIFIED（R6 rerender 已闭环；R7 real-remote 补证仍需闭环；ledger unresolved） |
| R6 Final Film 与最终 SRT | task-contracts/V1-R6-FINAL-FILM-SUBTITLE-DELIVERY-20260908.md | VERIFIED（同候选真 FFmpeg / SRT / PG 通过；ledger unresolved） |
| R7 双创作路径与真实用户验收 | task-contracts/V1-R7-DUAL-PATH-REAL-ACCEPTANCE-20260908.md | IN PROGRESS（隔离运行栈与真实验收） |
| R8 最终候选与发布准备 | pending bounded supplement | BLOCKED BY R7 |
