# Task Contract: Director Shared Workspace Evidence

**Status:** COMPLETED

**Date:** 2026-08-13

**Responsibility:** Provide bounded automated evidence that the Quick Director
workspace and professional production workspace read the same recoverable
Director project truth. This contract is subordinate to the active product,
runtime, quality, and roadmap contracts; it does not close a release Gate.

## Outcome

For a Director-controlled project, the professional production route reads the
same `workspace-snapshot` query key used by the Quick workspace, presents the
current workflow, locked artifacts, production batches, reservations, steps,
and issues, and withholds legacy P0 execution controls.

## Scope

- Render shared Director facts in `projects.$projectId.production.tsx` from
  `GET /api/v1/projects/{id}/director/workspace-snapshot`.
- Prevent the legacy script-import, shot-operation, and legacy-export controls
  from being used for a Director-controlled project.
- Add focused frontend coverage for the professional shared-facts view.
- Add backend snapshot lineage coverage for locked storyboard, batch, and
  budget reservation records.
- Record the resulting bounded evidence in the release Gate board and live
  execution checkpoint.

## Out Of Scope

- Real Provider calls, Provider spend, or evidence collection.
- A source-bound live-stack browser scenario on a clean candidate.
- Changing Director confirmation, authorization, repair, or delivery policy.
- Declaring Gate A2 passed, publishing a release, or modifying unrelated
  legacy P0 behavior outside the Director-controlled guard.

## Owned Paths

- `frontend/src/routes/projects.$projectId.production.tsx`
- `frontend/src/styles/index.css`
- `frontend/tests/unit/WorkstationShell.test.tsx`
- `backend/tests/unit/test_director_snapshot_api.py`
- `docs/task-contracts/director-shared-workspace-evidence.md`
- `docs/runbooks/release-gate-board.md`
- `docs/开发执行检查点.md`

## Acceptance Evidence

- Frontend unit coverage shows the professional workspace renders a Director
  workflow identifier, locked artifact revision, production batch, and linked
  reservation from the shared snapshot while legacy controls are absent.
- Backend unit coverage proves the snapshot retains the locked storyboard,
  trial batch, and budget reservation/authorization lineage.
- `ruff`, `mypy`, targeted backend tests, frontend tests, typecheck, lint, and
  production build pass locally.
- Gate A2 remains `PARTIAL` until one clean candidate has a live-stack browser
  scenario that edits, reads, and compares the same records in both modes.

## Completion Definition

The professional view uses the same Director snapshot truth as Quick mode and
cannot offer a parallel legacy execution path for Director-controlled projects.
The remaining live-stack, source-bound A2 release evidence is explicitly
recorded rather than inferred from unit or mocked-browser tests.
