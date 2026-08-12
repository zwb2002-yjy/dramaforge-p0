# Task Contract: Director Real Provider Evidence Preflight

**Status:** COMPLETED

**Date:** 2026-08-13

**Responsibility:** Define the bounded operational procedure required before
collecting real Provider evidence for the Director release gates. This Task
Contract is subordinate to the active product, quality, and roadmap contracts;
it does not grant budget authorization or supersede any release Gate.

## Outcome

Provide one repeatable, source-bound preflight and evidence procedure for Q0,
Q1, Gate A3, and Gate A4. The procedure must make every real paid request
depend on a separate written authorization, a clean candidate, frozen binding
and inputs, capability/pricing/reference/license checks, and sanitized evidence.

## Scope

- Add `docs/runbooks/real-provider-evidence-preflight.md`.
- Link the Gate board's next actions to the preflight procedure without closing
  a Gate.
- Update the live execution checkpoint with the documentation work and the
  remaining source-freeze and real-evidence boundary.

## Out Of Scope

- Making a real Provider call, spending funds, or granting authorization.
- Freezing, committing, staging, or cleaning the existing dirty worktree.
- Changing Provider runtime behavior, quality policy, Selection Plan, or
  release status.
- Treating a Spy test or historical evidence as a real-provider result.

## Owned Paths

- `docs/runbooks/real-provider-evidence-preflight.md`
- `docs/task-contracts/director-real-provider-preflight.md`
- `docs/runbooks/release-gate-board.md`
- `docs/开发执行检查点.md`

## Acceptance Evidence

- The runbook has explicit clean-candidate, per-run written authorization,
  capability, pricing/reservation, reference-lineage, and license-inventory
  preconditions.
- It defines redacted evidence files beneath
  `tmp/p0-evidence/<commit>/real-provider/` and explicitly excludes secrets,
  private prompts, raw media, URLs/grants, and participant identities.
- It distinguishes `PASS`, `BLOCKED`, and `ABORTED`, and states that a
  successful API call alone cannot close Q1/A4 or the release gate.
- The Gate board remains `OPEN` or `PARTIAL` until a clean candidate and real
  evidence are reviewed.
- `git diff --check` passes.

## Completion Definition

The operational documentation is present, linked from the evidence tracker and
checkpoint, and preserves the explicit-authorization boundary. No paid request
or Gate decision was made while completing this task.
