# Task: Acceptance repair Git closeout — 2026-09-06

## State and Owner authority

- State: LOCAL CANDIDATE VERIFIED; commit/push and exact-head remote checks are the next gates. Final GitHub integration facts belong to PR #12, not this pre-commit status.
- Owner request in the current task: “完成这些，提交合并”. This explicitly authorizes committing, pushing and merging the already-approved A01/A02/A03 repairs using the authenticated Owner account, subject to all repository checks. It supersedes the earlier repair contracts' no-push/no-merge scope only for this batch.
- Use the existing dev → main PR #12. Do not self-approve a review, use an administrator bypass, force-push, change protections, or write a MERGED ledger event. Ordinary repository rules remain unchanged; the explicit Owner instruction is not standing authority for later merges.
- This does not approve vNext implementation, model calls/fees, new production writes, release tags, publication workflow dispatch, or replacement of the local deployment.

## Current evidence and selection

- Baseline: dev@1b847ce319e886480f7bb2c7acd2c91744077df6, eight existing local commits ahead of origin/dev. Those already-committed September 4 fixes remain part of normal dev integration.
- Select only the 32 repair code/test/config paths below. ReviewWorkspace and production-page use partial staging to exclude pre-existing navigation tabs/import/copy; the original files are not overwritten.
- Unrelated navigation, route-shell and Agent-instruction edits remain local. All 65 pre-existing dirty files/deletions were backed up with hashes before staging.
- A clean selected-source archive was materialized from Git tree `66582bbe808080d4debc6fcda649e503d90bb2e2`. This is a validation copy, not a new Git worktree or a workaround for the root-clean guard.

## Outcome / success criteria

- Commit the approved fixes without including or discarding unrelated work.
- Push dev, update the existing PR's stale evidence, and require the current HEAD's policy, container-gates and security checks to pass before the Owner-requested merge.
- Preserve main's protected PR path and the local runtime/data. Verify remote merge identity and preservation hashes afterward.
- Report code integration separately from full-project acceptance, paid Golden, clean-commit deployment and formal Task ledger completion.

## Owned paths

- `backend/app/api/v1/editing.py`
- `backend/app/api/v1/final_film.py`
- `backend/app/api/v1/review.py`
- `backend/app/editing/adapter.py`
- `backend/app/production/final_film.py`
- `backend/tests/integration/test_phase10_rls_modelres_audit_pg.py`
- `backend/tests/unit/test_compose_contract.py`
- `backend/tests/unit/test_editing_api.py`
- `backend/tests/unit/test_final_film_api.py`
- `backend/tests/unit/test_final_film_timeline.py`
- `backend/tests/unit/test_professional_workspace_api.py`
- `frontend/nginx.conf`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/src/features/editing/EditingSessionPicker.tsx`
- `frontend/src/features/editing/FinalFilmPlayback.tsx`
- `frontend/src/features/editing/editing-recovery.css`
- `frontend/src/features/editing/api.ts`
- `frontend/src/features/production/ProfessionalWorkbench.tsx`
- `frontend/src/features/review/VideoReviewTimeline.tsx`
- `frontend/src/features/review/video-review.css`
- `frontend/src/features/scenes/SceneWorkspace.tsx`
- `frontend/src/lib/queryKeys.ts`
- `frontend/src/routes/projects.$projectId.edit.tsx`
- `frontend/src/routes/projects.$projectId.scenes.$sceneId.tsx`
- `frontend/src/shared/api/generated.ts`
- `frontend/tests/unit/EditingWorkspace.test.tsx`
- `frontend/tests/unit/EditingRecovery.test.tsx`
- `frontend/tests/unit/VideoReviewFlow.test.tsx`
- `frontend/tests/unit/ProfessionalWorkbench.test.tsx`
- `frontend/tests/unit/SceneWorkspace.test.tsx`
- `frontend/src/features/review/ReviewWorkspace.tsx`
- `frontend/src/routes/production-page.tsx`

- The A01/A02/A03 contracts, this closeout contract, and `docs/reviews/acceptance-repair-20260906.md`.
- Task-local evidence under `tmp/acceptance-git-closeout-20260906/` (not committed).

## Validation already completed

- Selected-source frontend: typecheck, lint, format, all 129 unit tests, build and generated API check PASS. The earlier mixed-worktree report's 134 tests includes unrelated navigation tests; that number is not reused as this selected candidate's count.
- All 458 selected-source backend files match the previously fully validated backend after Git line-ending normalization: 895 unit, 20 PostgreSQL integration, 5 real-proxy/mock-upstream integration tests; Ruff, mypy, migrations and canonical checks passed in that earlier run.
- Previous built-in-browser repair-flow evidence remains valid for the unchanged repair implementations; the excluded navigation shell itself is not claimed as part of this commit. Exact-head remote container gates must still run on the selected commit.
- Staged diff whitespace checks pass. No dependency or CI assertion changes were made to silence warnings or skip failures.

## Ledger constraint

The root dev worktree intentionally retains unrelated Owner changes, so the existing root-clean ledger guard remains unsatisfied. Do not stash, commit, clean, forge history, or alter the guard just to fabricate a COMPLETED event. This limitation does not constitute a failed Git push/merge, and code integration must not be labelled whole-Goal or formal Task completion.

## Evidence

- `tmp/acceptance-git-closeout-20260906/preservation-before.json`
- `tmp/acceptance-git-closeout-20260906/selection.json`
- `tmp/acceptance-git-closeout-20260906/selected-tree.json`
- `tmp/acceptance-git-closeout-20260906/selected-frontend-results.json`
- `tmp/acceptance-git-closeout-20260906/source-equivalence.json`
- `docs/reviews/acceptance-repair-20260906.md`
