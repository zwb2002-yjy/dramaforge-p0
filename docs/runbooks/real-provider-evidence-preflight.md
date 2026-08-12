# Real Provider Evidence Preflight

**Status:** LIVE / operational preflight, not spend authorization

**Version:** 1.0

**Date:** 2026-08-13

**Responsibility:** Collect source-bound, sanitized evidence for Q0, Q1, Gate
A3, and Gate A4 before and after a specifically authorized real Provider run.
This runbook implements the active release and quality contracts; it does not
replace them and does not authorize product, runtime, or budget changes.

## Purpose And Boundary

Use this runbook for every paid or otherwise externally billed Provider run,
including a keyframe, representative trial, formal production, repair, or
golden sample. It makes the authorization and evidence boundary explicit before
the request is submitted.

This document never grants spend. A real submission is permitted only after the
Owner or delegated authorizer gives separate, written, per-run approval. A
successful API response alone does not close Q1, A3, or A4: the required
authorization, frozen binding, effective-request translation, reference lineage,
cost, and sanitized post-run evidence must all be present.

Do not use historical P0 reports, mocked browser flows, Spy-only tests, or a
dirty worktree as a substitute for this procedure. Automated Spy coverage is a
useful prerequisite for A4/Q1, but real-provider evidence remains required.

## Roles

| Role | Responsibility |
|---|---|
| Owner / delegated authorizer | Gives written per-run authorization and the maximum spend. |
| Run operator | Performs this checklist, stops on a blocker, and preserves evidence. |
| Reviewer | Verifies the evidence index and updates the release Gate board. |

The authorizer may also be the run operator only when the written approval
exists before submission. The source authorization record is access-controlled;
Git and shared evidence receive only its opaque identifier and redacted facts.

## Entry Criteria

All conditions below must be true before a request may be submitted:

1. The candidate is a committed source revision and `git status --porcelain`
   produces no output. Record the full `git rev-parse HEAD` value.
2. The running API and worker identify the same source commit as the candidate.
   Do not collect evidence from a stack assembled from uncommitted files.
3. The run has a written authorization that has not expired.
4. The selected Provider connection, endpoint, model, revision, and frozen
   model binding are known and match the Selection Plan.
5. The pricing snapshot, requested budget, and reservation are available for
   the exact run scope. Unknown pricing is a block, not an invitation to guess.
6. The capability manifest confirms the required modality, aspect ratio,
   duration, reference mechanism, native-audio behavior, and requested advanced
   parameters.
7. Every required Canonical, first-frame, or other reference Artifact is
   readable, allowed for this binding, and has a recorded immutable hash.
8. The model, weight, voice, and other resource license inventory is complete
   enough for the selected release path.

## Written Authorization Record

Create this record outside Git in an access-controlled location. The record
must name the actual Owner or delegated authorizer. Its sanitized evidence copy
must contain only `authorization_id`, role, date, expiry, scope, currency, and
maximum amount; it must not contain a name, signature image, credentials, or a
payment instrument.

```text
authorization_id:
owner_or_delegated_authorizer_name:
authorizer_role:
issued_at_local:
expires_at_local_or_stop_condition:
candidate_commit:
run_scope: trial / keyframe / production / repair / golden sample
project_or_sample_pseudonym:
provider_binding_id:
provider_endpoint_and_model_revision:
maximum_spend_amount:
currency:
included_attempts_and_retry_rule:
stop_condition:
```

The authorization scope must be narrow. A repair, expanded shot set, changed
binding, changed price, or paid retry outside the stated attempt rule requires
new written authorization and a new preflight decision.

## Preflight Procedure

1. Create `tmp/p0-evidence/<commit>/real-provider/`. Use the exact clean
   candidate commit, not a branch name or shortened hash.
2. Record `preflight-decision.json` with the candidate commit, operator,
   timestamp, decision, blocker codes when applicable, and the opaque
   authorization ID. Do not include credentials or personal identities.
3. Save `frozen-inputs.json`: workflow/version, project or sample pseudonym,
   Selection Plan ID/hash, model binding ID, Provider/model/revision, aspect
   ratio, duration, audio setting, and hashed provider-independent intent.
4. Save `capability-pricing.json`: capability manifest ID/hash and relevant
   declared slots/constraints, pricing snapshot ID/hash, maximum authorized
   amount/currency, and reservation ID/amount. Do not include a secret endpoint
   URL or account balance.
5. Save `reference-lineage.json`: each required Artifact ID, SHA-256, role,
   character binding, injection location, MIME type, and availability result.
   Exclude raw media, object keys, permanent URLs, signed URLs, and download
   grants.
6. Save `license-inventory.json`: resource identifier, source record,
   license-review state, reviewer role, and known limitation. Do not claim an
   unreviewed weight or voice is release-compatible.
7. Confirm the submission path will persist a sanitized
   `ProviderOperation.request_summary.compiled_request` and a
   `TranslationReport`. Required-parameter loss must fail closed before the
   external call.
8. Mark the preflight `PASS` only when every entry criterion is evidenced. A
   preflight pass permits the one authorized submission; it is not a release
   Gate pass.

## Submission And Stop Rules

Submit only the scope explicitly authorized. Preserve the normal application
ledger; do not manually recreate a request in a Provider console merely to
obtain evidence.

Set the preflight decision to `BLOCKED` and do not submit when authorization is
missing or expired, the candidate is dirty, the binding/capability mismatches,
pricing or reservation is unknown, a required reference is unavailable, or the
license inventory is incomplete. Record the blocker code and safe diagnostic
only.

Set the run to `ABORTED` after submission when the stop condition is reached,
the actual cost would exceed the authorization, the response makes submission
state unknown, an unexpected binding is observed, or a required evidence item
cannot be safely retained. Do not issue an additional paid retry without fresh
authorization. Preserve the evidence gathered so far and update the ledger with
the real outcome.

## Required Post-Run Evidence

For any submitted request, retain these sanitized files under the same evidence
directory:

| File | Required contents |
|---|---|
| `effective-request.json` | Provider, endpoint alias, model/revision, binding, intent hash, idempotency hash, aspect ratio, duration, native-audio setting, applied/degraded/rejected parameters, reference Artifact hashes and injection locations. |
| `translation-report.json` | TranslationReport result and whether every required parameter survived. |
| `operation-summary.json` | ProviderOperation ID, redacted request/response identifiers, submission status, latency, actual cost/currency, and sanitized compiled request summary. |
| `reference-lineage.json` | Updated lineage when the persisted operation identifies a more precise injection result. |
| `postrun-index.json` | All evidence filenames, SHA-256 values, decision, reviewer, source commit, and Gate IDs supported or still open. |

Never store in Git or the evidence directory: credentials, API-key fragments,
raw prompts containing participant/private content, raw media, object storage
keys, permanent or signed URLs, download grants, raw Provider responses that
carry any of those values, participant identities, or payment details. Keep
only the minimum hashes, aliases, opaque IDs, and redacted summaries required
to establish lineage and behavior.

## Decision And Gate Update

After review, append one redacted row to
[`release-gate-board.md`](release-gate-board.md). Use this template:

```markdown
| YYYY-MM-DD | Q0, Q1, A3, A4 | OPEN/PARTIAL -> PARTIAL/PASS | <full commit> | tmp/p0-evidence/<commit>/real-provider/ | <reviewer role> | Authorization <opaque ID>; scope <scope>; cost <amount currency>; result <pass/blocked/aborted>; known limits <summary>. |
```

Only change a Gate status after the reviewer has checked the complete index and
the active contracts' required evidence. A single successful call may support a
`PARTIAL` status, but cannot claim a full-work, user-study, installation, or
release pass that it did not exercise.
