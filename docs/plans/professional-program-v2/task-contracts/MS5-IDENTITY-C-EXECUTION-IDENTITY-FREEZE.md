# Task: MS5-IDENTITY-C — Execution Identity Freeze

## Status

- **State:** COMPLETE
- **Program order:** `MS5-IDENTITY-A` → `MS5-IDENTITY-B` → `MS5-IDENTITY-C` → Phase 4 Merge Gate
- **Task boundary:** Define and persist the full secret-free execution identity, and make existing Professional poll/resume/cancel reconstruction consume the frozen connection/credential/model identity. Do not enter the Phase 4 Merge Gate or add new runtime/worker/generation abstractions.

## Read first

- [`../README.md`](../README.md)
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) §9 and the execution-identity completion rules
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §14
- Completed `MS5-IDENTITY-A-IMMUTABLE-CREDENTIAL-REVISION.md`
- Completed `MS5-IDENTITY-B-PROVIDER-CONNECTION-REVISION.md`
- Current `ExecutionModelResolution`, `ProviderRuntimeResolver`, `ProviderOperation`, `NodeRun`, Professional unified submission/resume code, and fake-runtime tests

## Current evidence / drift

- MS1–MS5 already persist model-selection, mode, references, and partial request evidence, and MS5-B adds `provider_connection_revision_id` to new Professional operations.
- `NodeRun.input_snapshot` and `ProviderOperation.selection_plan` are not yet normalized around one typed `ExecutionIdentitySnapshot` containing every required model, catalog, connection, credential, capability, mode, options, reference, translation, and fingerprint field.
- Unified resume currently loads the mutable current `ProviderConnection` and calls `resume_runtime()` from its current host/protocol/credential lookup. That can select a newer account/endpoint after a submitted operation is resumed.
- Existing fake runtimes and persisted `ProviderResumeToken` are suitable for a no-network proof; no real or paid Provider call is authorized.

## Objective

Make the execution identity explicit, secret-free, and durable before the first Provider request. After submission, retries, worker restarts, poll, and cancel must reconstruct the runtime from the frozen connection revision, credential revision, model binding/catalog facts, and persisted resume token rather than current mutable configuration.

## Required behavior

1. **Typed identity contract**
   - Add a Pydantic/dataclass `ExecutionIdentitySnapshot` (no new ORM) with at least:
     - `requested_model`
     - `resolved_model`
     - `resolution_source`
     - `provider_model_binding_id`
     - `catalog_entry_id`
     - `model_revision`
     - `manifest_hash`
     - `invoke_model_value`
     - `connection_id`
     - `connection_revision_id`
     - `credential_revision_id`
     - `capability`
     - `mode_id`
     - `effective_options`
     - `resolved_references`
     - `translation_report`
     - `request_fingerprint`
   - Identity must be serializable to JSON, contain no plaintext/ciphertext/headers/download grants, and reject mutation in process (`frozen`/immutable model semantics).
2. **Freeze at first submission**
   - Build the identity only after concrete model/runtime resolution and request compilation, immediately before persisting `submission_started` and making the Provider create call.
   - Write the same identity (JSON-safe) into `NodeRun.input_snapshot`, `ProviderOperation.selection_plan`, and a sanitized `ProviderOperation.request_summary` evidence section.
   - Preserve existing compatibility keys and existing mode/reference/translation evidence while making the typed identity authoritative.
   - For rejected no-remote retries, keep the prior frozen identity if it exists; do not silently switch to current connection/model defaults.
3. **Revision-aware runtime reconstruction**
   - Resolve the operation's `ProviderConnectionRevision` by its frozen id, verify workspace/connection ownership, provider type, protocol profile, base URL, and concrete credential revision identity.
   - Reconstruct a runtime using the immutable revision values and `read_credential_by_id` for the frozen credential revision. Do not use current `ProviderConnection.base_url`, current `credential_id`, or provider-key default lookup for existing operations.
   - Poll, cancel, cost fetch, and resume after worker restart must use the frozen revision and persisted `ProviderResumeToken`; they must never submit a second remote task or re-run model selection.
4. **Consistency and fail-closed rules**
   - If any required identity component or revision is missing/mismatched, fail closed with a structured non-secret error before network traffic.
   - Existing legacy operations with no frozen identity remain compatible but cannot claim the new Professional identity guarantee; new Professional operations must always have it.
   - Do not expose secret values in API responses, NodeRun snapshots, ProviderOperation selection plans, request/response summaries, errors, or logs.

## Owned paths

- `backend/app/providers/execution_identity.py`
- `backend/app/providers/runtime.py`
- `backend/app/providers/workspace_credentials.py`
- `backend/app/execution/models.py`
- `backend/app/execution/product_path.py`
- `backend/app/workers/jobs.py`
- `backend/tests/unit/test_execution_identity.py`
- `backend/tests/unit/test_unified_path.py`
- `backend/tests/unit/test_runtime_model_resolution.py`
- `docs/plans/professional-program-v2/task-contracts/MS5-IDENTITY-C-EXECUTION-IDENTITY-FREEZE.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- Phase 4 Merge Gate or manual production alpha.
- New ORM tables/migrations (MS5-A/B schema is sufficient).
- New Worker/Runtime/Generation abstraction; extend existing resolver/runtime seams only.
- Real Provider traffic, paid calls, live PostgreSQL apply, or unrelated legacy cleanup.

## Verification gate

- Focused identity and unified-path tests prove:
  - the typed identity is complete, immutable, JSON-safe, and secret-free;
  - a new operation writes the same identity to NodeRun and ProviderOperation evidence;
  - rev1 submission followed by connection/credential update to rev2 and worker restart/resume still uses rev1 host and credential;
  - poll/cancel never re-submit and never reselect a model;
  - missing/mismatched frozen identity fails closed without a Provider call.
- Existing backend unit suite passes: `717 passed`.
- `ruff check app tests alembic/versions`: All checks passed.
- `mypy app`: Success: no issues found in 185 source files.
- PostgreSQL integration runs only when enabled and reachable; otherwise record a truthful skip.
- Only after this contract is complete may the project enter the separately gated Phase 4 Merge Gate audit.
