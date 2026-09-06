# Task: ACCEPTANCE-A02 — Real video review and explicit time annotations

- State: IMPLEMENTED / VERIFIED IN WORKTREE (uncommitted; not formal COMPLETED); Owner approved the three-item repair batch in this thread.
- Task id: acceptance-a02-video-review-20260906.
- Authority: 01 review/candidate facts, 02 §29, 06 canonical invariants, 03 §53–55; existing P6-REVIEW-UI rendering contract remains historical evidence, not full product acceptance.
- Current evidence: Review loads a formal keyframe but has no video player or time annotation input; the existing video component only renders saved annotations.
- Outcome: playable current formal video, seek/current-time point or range selection, explicit validated note submission and reload through existing ReviewAnnotation; no change to Formal/Shot/production truth.
- Owned paths: frontend/src/features/review/*; frontend/tests/unit/ReviewUI.test.tsx and focused ReviewWorkspace tests; backend/app/api/v1/review.py and focused annotation tests; current contract and task evidence.
- Constraints: preserve pre-existing navigation changes in ReviewWorkspace; no Provider, repair execution, schema migration or paid call. Use seconds as current API contract; enforce finite ordered in-media bounds and nonblank note. Switching Shot/media must reset draft coordinates; stale completion must not clear another shot's note.
- Verification: player/error/point/range/no-write-before-save/rejected-range/reload/shot-switch tests, backend ownership/CSRF/type/range regressions, frontend lint/type/unit/build, API contract unchanged, real in-app browser playback and UI controls. Final combined current-source PostgreSQL and browser gate required. No formal COMPLETED without required evidence/commit; ledger STARTED remains unavailable due pre-existing dirty root guard (no bypass/forged log).


## Verification / handoff
- Implemented under the Owner-approved scope. Combined evidence: D:/dramaforge/tmp/acceptance-repair-20260906/REPAIR-REPORT.md.
- Frontend 134 unit tests; backend 22 targeted tests plus 1 gateway contract test; 8 real PostgreSQL/RLS tests; type/lint/build/API checks and in-app browser verification passed.
- Existing film playback/download and creative-data preservation are documented with media metadata, hashes and read-only counts. No paid generation or live test annotation was submitted.
- Latest local runtime/recipe: build-identity-r5.json and runtime-compose-r5.yml in that evidence directory. Source remains a dirty worktree; no commit, remote release, PR merge, formal COMPLETED ledger entry or whole-Goal completion is claimed.

## 2026-09-06 Owner-authorized Git closeout

The earlier handoff above records the pre-submission state. The Owner subsequently requested “完成这些，提交合并”. Commit/push and the checked dev → main integration of this repair batch are now authorized by [the bounded closeout contract](ACCEPTANCE-REPAIR-GIT-CLOSEOUT-20260906.md). Unrelated navigation and instruction edits, new vNext runtime, paid generation and deployment changes remain excluded. Selected-source frontend checks pass (129 tests); exact-head CI/merge evidence is tracked in PR #12. No formal COMPLETED/MERGED ledger or whole-project acceptance is implied.
