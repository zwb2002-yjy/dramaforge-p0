# V1 G7C — Workbench media dispatch pure-upstream fix

**Task:** `v1-g7c-media-upstream-fix-20260903`
**Status:** COMPLETE
**Goal:** DramaForge V1 统一创作主链 — G7/G8 media runtime

## Problem found in audit

The unified Workbench `executions` route queues only the concrete media
NodeRun (keyframe/video).  After legacy cleanup the frozen shot graph still
declared a required pure `prompt` upstream; the real Worker failed any media
run with `UPSTREAM_RUN_MISSING: prompt`.  UI/E2E mocks could not expose this.

## Fix

`WorkbenchExecutionService.create_and_dispatch` now materializes missing pure
upstream NodeRuns (`prompt`/`prompt_compose`) as queued zero-provider facts in
the same shot graph before the media run is enqueued.  The Worker executes the
pure run first and the media run retries/defer until its dependency is ready.

## Owned Paths

- `backend/app/production/workbench_execution.py`
- `backend/tests/unit/test_workbench_execution.py`
- `docs/plans/professional-program-v2/task-contracts/V1-G7C-MEDIA-UPSTREAM-FIX-20260903.md`

## Verification

- focused `test_workbench_execution.py` + formal selection + repair 23 passed；
- real current-HEAD Golden completed all three keyframe/video provider runs
  (`docs/reviews/GOLDEN-V1-CURRENT-HEAD-20260903.json`).
