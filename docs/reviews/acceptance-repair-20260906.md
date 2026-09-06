# Acceptance repair batch — integration evidence

## Scope

Owner-approved A01 editing-session/Final Film recovery, A02 real video review/time annotations, and A03 contextual Director entry. Includes the reproduced stale-HTML and narrow-layout delivery corrections. Existing canonical production identity, Formal selection and Editing/Production boundaries are preserved.

The Owner explicitly requested commit and merge on 2026-09-06. The detailed selection and authorization are in the [closeout contract](../plans/professional-program-v2/task-contracts/ACCEPTANCE-REPAIR-GIT-CLOSEOUT-20260906.md). Use existing PR #12 from dev to main; do not treat its historical release-candidate paragraph or older Golden as current-head evidence.

## Local validation

| Gate | Result / source identity |
|---|---|
| Selected-source frontend typecheck / lint / format / build | PASS |
| Selected-source frontend unit suite | 129 PASS; unrelated navigation tests excluded with their implementation |
| Selected-source generated API | PASS against the repaired backend schema |
| Backend unit | 895 PASS on content-equivalent source |
| PostgreSQL integration | 20 PASS, no skipped tests, isolated database |
| Real pinned proxy integration | 5 PASS, mock upstream, no paid Provider calls |
| Backend Ruff / mypy / migrations / canonical checks | PASS on content-equivalent source |
| Built-in browser repair flows | Prior local repair build: existing sessions, real playback/download, explicit review controls, contextual Director drill-through and responsive layout |
| Git diff whitespace | PASS |

The selected code tree is `66582bbe808080d4debc6fcda649e503d90bb2e2`. The full exact-commit remote CI is a separate required gate; its final result and merge commit are reported by PR #12 after push. This file intentionally does not claim a pre-commit remote pass.

## Media and preservation evidence

- The pre-existing Wuzhen Final Film played through about 15.17 seconds. The downloaded 8,604,429-byte MP4 matched SHA-256 `5f3acb71912f980d4e983164b4ed7064133ead80cffbdd3033037189595c5753`.
- No live annotation, Director request, production execution, Timeline save or re-export was submitted during browser QA. Persistence/write cases ran in isolation.
- Navigation and Agent-instruction edits are not included in this repair commit; their local file bytes are preserved. The two overlapping files use selective staging only.
- The local service remains the worktree acceptance build `worktree-acceptance-20260906-32216450fd43`; committing/merging does not silently redeploy it or relabel it as a clean-commit release.
- No credentials, raw Provider payloads, signed media URLs or binary evidence are included here.

## Limits

Code integration is not whole-project acceptance or a new paid Golden. The vNext Runtime is not implemented by this batch. The root-clean lifecycle guard remains blocked by preserved unrelated edits, so no formal COMPLETED or MERGED ledger entry is fabricated. There is no release tag, publication dispatch, direct main push or branch-protection bypass.

Detailed local logs, preservation hashes and exact source records remain under `D:/dramaforge/tmp/acceptance-repair-20260906/` and `D:/dramaforge/tmp/acceptance-git-closeout-20260906/`.

## Exact-head browser gate follow-up

The first remote run on `f7d84e1` found two obsolete E2E scenarios that still clicked the removed canned suggestion's “采纳” button. They now traverse Production → exact Scene/Shot Director → explicit suggestion request → preview → local draft apply → versioned design save → reload. The fixture persists Director design state and the request assertions reject creative writes before explicit save; the existing last-view preference PATCH is separately checked for its exact navigation-only shape. Canvas, asset, review, Director board and experiment assertions are retained. The duplicated workflow mock was replaced with the repository's shared fixture.

The selected-source follow-up passed typecheck, lint, formatting, the two focused scenarios and all 15 browser E2E tests with no skips. APIs are intercepted by controlled fixtures and the local fallback API is bound to an unused endpoint, not the live service. No application code, timeout, retry, dependency or CI gate was changed. The current-head remote checks remain a separate required gate before merge.
