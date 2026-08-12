# Task Contract: Controlled Post-Media Content Change Lineage

**Status:** COMPLETED

**Date:** 2026-08-13

**Responsibility:** Extend the existing confirmed-change command so a creator can
revise locked story or shooting facts after media evidence exists, without
deleting historical media lineage, silently reusing invalid outputs, or leaving
spend authorization active for an obsolete plan.

This bounded task is subordinate to the active product, runtime, quality, and
roadmap contracts. It does not authorize a Provider call, user study, or
release-Gate status change.

## Decision

The implementation supports a post-media content change only when every prior
production batch is static. A static batch has a terminal or review state and
no queued, leased, or running NodeRun. A batch in `materializing`,
`authorized`, or `running` blocks both proposal creation and confirmation. A
static batch may still have a `reserved` amount that was never settled; explicit
change confirmation releases that unused reservation. This task deliberately
does not cancel active Provider work.

Allowed workflow states for a proposal are the existing no-media states plus:

- `awaiting_production_authorization` after an accepted trial;
- `repair_proposed` and `awaiting_repair_authorization` after a static batch;
- `final_review` after production inspection; and
- `completed` after a delivery export.

`trial_running`, `production_running`, and `assembling` remain prohibited.

## Confirmed Change Semantics

On an explicit confirmation with a fresh base version:

1. Existing creative versions downstream of the target become `superseded`;
   historical records are never overwritten or deleted.
2. Historical static batches become `superseded_by_change`; their immutable
   locked version references, NodeRuns, ProviderOperations, Artifacts, quality
   evidence, and delivery records remain readable.
3. Any still-active authorization attached to a superseded batch is revoked.
4. A non-settled reservation is changed from `reserved` to `released`, with its
   amount never copied into a later authorization. Settled, overrun, and
   settlement-error reservations remain unchanged so actual spend stays
   auditable.
5. The proposal impact names affected batch IDs, released reservation IDs,
   settled historical cost, and only Artifact IDs that are eligible for future
   semantic reuse. In this first slice a changed StoryCore has no eligible
   media reuse, because all shooting facts must be regenerated and re-approved.
6. The workflow returns to `awaiting_creative_confirmation` for creative
   changes or `awaiting_shooting_confirmation` for shooting changes. New
   shooting approval, a new budget authorization, and a new batch are required
   before any further media submission.

## Concurrency And Recovery

- The existing proposal idempotency key returns the original impact report.
- Confirmation is idempotent after a successful apply.
- Proposal creation, budget authorization, batch materialization, and
  confirmation serialize on the workflow row. Confirmation additionally locks
  its proposal, batches, active NodeRuns, reservations, authorizations, and
  relevant approvals before re-checking static state.
- The paid-media submission guard locks the same workflow, batch, reservation,
  and authorization rows before accepting a new Provider submission. A worker
  released after a confirmed change therefore sees the superseded batch or
  revoked authorization and fails closed before an external request.
- Releasing a reservation is idempotent: only `reserved` changes to `released`.
  No settled amount is refunded or mutated.

## Out Of Scope

- Cancelling a submitted/running Provider operation.
- Automatic refund, provider-side cancellation, or settlement reconciliation.
- Reusing media after a semantic StoryCore or shooting-plan change.
- Real Provider calls, costs, quality claims, or user-study evidence.

## Owned Paths

- `backend/app/director/service.py`
- `backend/app/director/execution_guard.py`
- `backend/app/director/production_service.py`
- `backend/app/director/repair_execution_service.py`
- `backend/app/director/snapshot_service.py`
- `backend/tests/unit/test_director_workflow_api.py`
- `backend/tests/unit/test_director_snapshot_api.py`
- `backend/tests/unit/test_director_execution_guard.py`
- `docs/task-contracts/director-post-media-change-lineage.md`
- `docs/runbooks/release-gate-board.md`
- `docs/开发执行检查点.md`

## Acceptance Evidence

- A static trial or production lineage can be proposed and confirmed through
  the existing controlled change API.
- The impact report exposes the affected batch, historical settled amount, and
  zero unsafe reuse for a StoryCore change.
- Confirmation preserves historical batch rows and settled reservations,
  invalidates approvals, revokes obsolete active authorization, and rejects any
  active batch or NodeRun.
- Snapshot and browser evidence show Quick and Professional reading the same
  revised version and superseded lineage without a Provider request.

## Completed Verification

- Backend focused Director workflow, snapshot, execution-guard, and production
  suites: `24 passed`.
- Backend static checks: `ruff` and `mypy` passed for the changed Director
  services.
- Backend full suite: `605 passed`.
- Frontend full lint passed. Prior unchanged UI coverage for this slice passed:
  typecheck, Vitest (`46 passed`), production build, and focused Director
  Playwright (`5 passed`).
- No Provider request, credential, paid execution, or user study was used for
  this implementation verification. A clean-candidate isolated live-stack
  scenario remains required before A2 can be reassessed.
