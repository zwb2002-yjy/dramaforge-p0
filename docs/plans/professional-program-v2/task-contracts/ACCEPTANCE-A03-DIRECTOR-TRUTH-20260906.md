# Task: ACCEPTANCE-A03 — Use the canonical, contextual Director flow

- State: IMPLEMENTED / VERIFIED IN WORKTREE (uncommitted; not formal COMPLETED); Owner approved replacement of static Director suggestions with the existing real contextual chain.
- Task id: acceptance-a03-director-truth-20260906.
- Authority: 01 §5/§6/§7 (one Director, no hidden second creative plan), 02 Director context/proposals, 06 single execution truth, 03 Phase 7; retain current Canvas-first and unified navigation amendments.
- Evidence: ProfessionalWorkbench generates three canned assertions for every selected Shot, including a false “检测到主角”.
- Outcome: remove that fabricated proposal list and its pretend AUTO/MANUAL state. Production's explicit Director entry opens the exact Scene+Shot in the existing ShotDirectorSuggestionPanel/ShotDesignPanel workflow. No second service or alternate editor state transfer. Suggestions remain real-context, explicit request → preview → explicit local apply → explicit save; no analysis or paid call on entry.
- Owned paths: frontend/src/features/production/ProfessionalWorkbench.tsx; frontend/src/routes/production-page.tsx; frontend/src/routes/projects.$projectId.scenes.$sceneId.tsx; frontend/src/features/scenes/SceneWorkspace.tsx; relevant frontend unit/E2E tests; this contract/evidence.
- Guards: no navigation with unsaved Production draft; explicit requested Shot must belong to the loaded Scene (fail closed if invalid); changing scope resets previews; no pre-existing navigation edits overwritten. Underlying canonical Proposal APIs stay intact.
- Verification: canned copy absent; exact project/scene/shot link; real contextual panel opens without POST; dirty and invalid-scope cases; existing Director request/partial apply/stale tests; current-source lint/type/unit/build and in-app browser drill-through. No new Runtime/provider/production writes.
- Lifecycle: independent bounded UI correction after A01 code and focused backend verification; final combined browser/PG gate pending. Existing root-dev-clean ledger guard prevents STARTED logging; no forged lifecycle status or clean/commit workaround.


## Verification / handoff
- Implemented under the Owner-approved scope. Combined evidence: D:/dramaforge/tmp/acceptance-repair-20260906/REPAIR-REPORT.md.
- Frontend 134 unit tests; backend 22 targeted tests plus 1 gateway contract test; 8 real PostgreSQL/RLS tests; type/lint/build/API checks and in-app browser verification passed.
- Existing film playback/download and creative-data preservation are documented with media metadata, hashes and read-only counts. No paid generation or live test annotation was submitted.
- Latest local runtime/recipe: build-identity-r5.json and runtime-compose-r5.yml in that evidence directory. Source remains a dirty worktree; no commit, remote release, PR merge, formal COMPLETED ledger entry or whole-Goal completion is claimed.

## 2026-09-06 Owner-authorized Git closeout

The earlier handoff above records the pre-submission state. The Owner subsequently requested “完成这些，提交合并”. Commit/push and the checked dev → main integration of this repair batch are now authorized by [the bounded closeout contract](ACCEPTANCE-REPAIR-GIT-CLOSEOUT-20260906.md). Unrelated navigation and instruction edits, new vNext runtime, paid generation and deployment changes remain excluded. Selected-source frontend checks pass (129 tests); exact-head CI/merge evidence is tracked in PR #12. No formal COMPLETED/MERGED ledger or whole-project acceptance is implied.
