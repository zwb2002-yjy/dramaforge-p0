# Task: ACCEPTANCE-A01 — Restore existing edit sessions and Final Film results

## Status / authority
- State: IMPLEMENTED / VERIFIED IN WORKTREE (uncommitted; not formal COMPLETED) (Owner approved this thread's three-item repair batch: “全部同意，立即修复”).
- Task id: acceptance-a01-editing-recovery-20260906.
- Authority: professional-program-v2 README; 01 §5/§79–81; 02 §79; 06 canonical execution boundaries; 03 §82–86; existing V1 Final Film async Timeline contracts.
- Baseline: dev@1b847ce plus pre-existing uncommitted navigation/rule changes. Audit: tmp/acceptance-audit-20260905/REPORT.md and SUPPLEMENT-20260906.md.

## Current evidence / drift
- Normal /edit entry only offers creating a new session although the live Wuzhen project has two existing sessions.
- Existing completed Final Film is persisted in Export/Artifact/NodeRun but disappears from the UI after reopening because exported results are component state only.

## Outcome
- Project-scoped, authenticated read-only session listing and exact-session render/result history.
- Explicit session selection/reopening, never implicit session creation or wrong-session selection; dirty Timeline cannot be silently discarded by the picker.
- Existing available Final Films have playback/download on reopening, with frozen Timeline version clearly distinguished from current version.
- Pending/failed/unavailable results remain understandable; queries never submit/retry/prepare/export media.

## Owned paths
- backend/app/api/v1/editing.py; backend/app/api/v1/final_film.py; backend/app/editing/adapter.py; backend/app/production/final_film.py
- frontend/src/features/editing/*; frontend/src/routes/projects.$projectId.edit.tsx; frontend/src/lib/queryKeys.ts; frontend/src/shared/api/generated.ts
- focused backend/tests/unit/test_editing_api.py, test_final_film_api.py and focused PG coverage; frontend/tests/unit/EditingWorkspace.test.tsx and new editing recovery tests.
- this contract; task-created tmp/acceptance-repair-* evidence.

## Protected boundaries / non-scope
No changes to existing creative facts, Provider/Worker execution, identity freezing, production schema or final selection; no new Runtime or paid call; preserve pre-existing edits. No production database migration required. No PR merge, publish, remote push, or cleanup of another session.

## Verification
- Focused API ownership/selected-workspace/wrong-project/wrong-session/empty-history and no-write regressions; frozen historical version isolation.
- UI existing/multiple/empty/error session list, selection, dirty draft guard, history reload, stale/missing media, project/session isolation.
- Current-source backend lint/types and focused unit/real PostgreSQL tests, generated API check; frontend lint/typecheck/unit/build; git diff --check.
- Local images explicitly labelled as worktree (not clean SHA), then in-app browser confirms real existing sessions and Wuzhen Final Film playback/download without re-export.
- Record actual commands/results and final diff. Uncommitted implementation is not formal COMPLETED or whole-project acceptance.

## Ledger constraint
The control.ps1 STARTED attempt was rejected by the existing root-dev-clean guard because this Owner workspace already contains uncommitted navigation/rule changes. No ledger entry was forged, no source was cleaned, and no commit was created. Implementation remains explicitly IN_PROGRESS under the Owner's direct approval; formal closeout must report this constraint.

Exact PG regression owned path: backend/tests/integration/test_phase10_rls_modelres_audit_pg.py (new recovery read-only/RLS test only).

## Browser-discovered delivery fix
Real navigation to /edit reused cached pre-repair HTML (index-C5Oh7FHv.js) while the running image served a different entrypoint. Additional owned paths: frontend/nginx.conf, backend/tests/unit/test_compose_contract.py, and the Scene→Editing route callback in SceneWorkspace / its route / tests. HTML now receives no-store, absent asset files return 404 rather than SPA HTML, and Scene→Edit uses route-owned client navigation. Preserve gateway security headers and verify real response headers plus navigation in the in-app browser. This fixes the reproduced A01 normal-entry blocker; no production data or new product scope.


## Verification / handoff
- Implemented under the Owner-approved scope. Combined evidence: D:/dramaforge/tmp/acceptance-repair-20260906/REPAIR-REPORT.md.
- Frontend 134 unit tests; backend 22 targeted tests plus 1 gateway contract test; 8 real PostgreSQL/RLS tests; type/lint/build/API checks and in-app browser verification passed.
- Existing film playback/download and creative-data preservation are documented with media metadata, hashes and read-only counts. No paid generation or live test annotation was submitted.
- Latest local runtime/recipe: build-identity-r5.json and runtime-compose-r5.yml in that evidence directory. Source remains a dirty worktree; no commit, remote release, PR merge, formal COMPLETED ledger entry or whole-Goal completion is claimed.

## 2026-09-06 Owner-authorized Git closeout

The earlier handoff above records the pre-submission state. The Owner subsequently requested “完成这些，提交合并”. Commit/push and the checked dev → main integration of this repair batch are now authorized by [the bounded closeout contract](ACCEPTANCE-REPAIR-GIT-CLOSEOUT-20260906.md). Unrelated navigation and instruction edits, new vNext runtime, paid generation and deployment changes remain excluded. Selected-source frontend checks pass (129 tests); exact-head CI/merge evidence is tracked in PR #12. No formal COMPLETED/MERGED ledger or whole-project acceptance is implied.
