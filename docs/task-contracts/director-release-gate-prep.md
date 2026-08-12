# Task Contract: Director Release Gate Preparation

**Status:** COMPLETED

**Date:** 2026-08-12

## Outcome

Create the operational materials needed to collect release evidence for the
`live_action_dialogue_short_v1` Director workflow without treating automation,
mocked browser flows, or historical P0 evidence as release approval.

## Scope

- Add a release Gate board that maps the active product, runtime, and quality
  contracts to concrete evidence and an accountable next action.
- Add an unmoderated target-user test runbook and one redacted participant
  record template for all three required sessions.
- Record the current implementation and verification boundary in the live
  execution checkpoint.

## Out Of Scope

- Running paid Provider calls or authorizing any external spend.
- Recruiting participants or collecting personal data.
- Closing Gate A, B, C, or the release checklist.
- Changing the product contract, workflow runtime, Provider behavior, or
  quality policy.

## Owned Paths

- `docs/task-contracts/director-release-gate-prep.md`
- `docs/runbooks/release-gate-board.md`
- `docs/runbooks/unmoderated-user-test.md`
- `docs/开发执行检查点.md`

## Acceptance Evidence

- The Gate board includes every release requirement from
  `docs/current/01-产品与发布契约.md` section 10,
  `docs/current/03-质量与验证体系.md` section 11, and
  `docs/current/04-执行路线图.md` section 8.
- Each evidence item says whether it is automated, real-provider, user-study,
  installation, or human-signoff evidence, and rejects mock or historical
  substitutions where required.
- The user-test script permits observation only and captures only pseudonymous,
  redacted records.
- `git diff --check` passes.

## Completion Definition

The materials are present, linked by the execution checkpoint, and correctly
show all release Gates as open until source-bound evidence is collected from a
clean candidate commit. Directory compliance and `git diff --check` passed.
