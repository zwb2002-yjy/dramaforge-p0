# Task: MS5-IDENTITY-B — ProviderConnectionRevision

## Status

- **State:** IN PROGRESS
- **Program order:** `MS5-IDENTITY-A` → `MS5-IDENTITY-B` → `MS5-IDENTITY-C` → Phase 4 Merge Gate
- **Task boundary:** Add immutable ProviderConnection revisions and freeze the revision identity on newly submitted Professional ProviderOperations. Do not implement ExecutionIdentitySnapshot, worker restart/resume reconstruction, poll/cancel runtime rebuilding, or Phase 4 merge work here.

## Read first

- [`../README.md`](../README.md)
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) §8.3
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §13
- Completed [`MS5-IDENTITY-A-IMMUTABLE-CREDENTIAL-REVISION.md`](MS5-IDENTITY-A-IMMUTABLE-CREDENTIAL-REVISION.md)
- Current `ProviderConnection`, `ProviderOperation`, connection service, Professional unified submission path, migration chain, and tests

## Current evidence / drift

- `ProviderConnection` is mutable configuration state. It has `base_url`, `protocol_profile`, `credential_id`, and a legacy `credential_revision` counter, but no immutable connection snapshot.
- `ProviderOperation` stores `connection_id` and other binding/catalog facts but has no `provider_connection_revision_id`.
- `create_connection()` and connection updates do not persist immutable connection revisions.
- Professional unified submission resolves current connection state immediately before creating `ProviderOperation`; a later connection update could otherwise make the operation ambiguous.
- MS5-IDENTITY-A already guarantees the credential row named by `connection.credential_id` is an immutable account revision and can be read strictly by id.

## Objective

Persist a lightweight immutable `ProviderConnectionRevision` for every effective execution configuration and make newly submitted Professional `ProviderOperation` rows point to the exact revision they used.

## Required behavior

1. **Schema / ORM**
   - Add `ProviderConnectionRevision` with at least:
     - `id`
     - `connection_id`
     - `revision_no`
     - `provider_type`
     - `protocol_profile`
     - `base_url`
     - `credential_revision_id`
     - `created_at`
   - Enforce positive revision numbers and uniqueness per `connection_id`/`revision_no`.
   - Foreign-key the revision to its connection and concrete immutable credential row; preserve prior revisions.
   - Add nullable `provider_connection_revision_id` to `ProviderOperation` with an index and restrictive foreign key.
   - Backfill one revision 1 for every existing ProviderConnection; existing operations may remain null because their historical identity predates this contract.
2. **Revision creation**
   - On connection creation, insert revision 1 using the concrete credential revision returned by MS5-IDENTITY-A.
   - When `base_url`, `credential_id`, or execution-relevant protocol configuration changes, insert the next immutable revision. Display name and enabled-only changes must not create a new execution revision.
   - Validate that the credential revision belongs to the same workspace/provider as the connection before creating a revision.
   - The current `ProviderConnection` remains the mutable configuration entity and points to the latest credential; no parallel connection truth is introduced.
3. **Operation freeze**
   - Immediately before a new Professional unified ProviderOperation is submitted, resolve the current connection revision and set `provider_connection_revision_id` on the operation.
   - Retried submission of the same existing operation must retain its previously frozen revision id; it must not switch to the current connection revision.
   - Existing legacy pipeline operations remain compatible with a nullable field and are out of scope for new identity semantics.
4. **Security / lifecycle**
   - Revision reads must be workspace-safe through the owning connection and must not expose plaintext credentials.
   - No real or paid Provider call is allowed in this task; fake runtime tests only.
   - Do not implement worker resume reconstruction; MS5-IDENTITY-C will consume this frozen field.

## Owned paths

- `backend/app/providers/models.py`
- `backend/app/providers/connection_service.py`
- `backend/app/execution/models.py`
- `backend/app/execution/product_path.py`
- `backend/alembic/versions/20260826_0042_provider_connection_revisions.py`
- `backend/tests/unit/test_connection_revisions.py`
- `backend/tests/unit/test_provider_connections.py`
- `backend/tests/unit/test_unified_path.py`
- `docs/plans/professional-program-v2/task-contracts/MS5-IDENTITY-B-PROVIDER-CONNECTION-REVISION.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- `ExecutionIdentitySnapshot` JSON/Pydantic contract (MS5-IDENTITY-C).
- Worker restart/resume/poll/cancel reconstruction from frozen revisions.
- New runtime/worker/generation abstractions, real Provider traffic, paid calls, or unrelated schema cleanup.

## Verification gate

- Focused revision-creation and operation-freeze tests pass, including:
  - initial revision 1;
  - credential/base URL changes produce revision 2 while old revision remains unchanged;
  - display/enabled-only changes do not create a revision;
  - a retry keeps the original operation revision after the connection moves to revision 2;
  - cross-workspace/foreign credential linkage fails closed.
- Existing backend unit suite passes.
- `ruff check app tests alembic/versions`, `mypy app`, directory compliance, migration offline SQL generation, and `git diff --check` pass.
- PostgreSQL integration runs only when configured and reachable; otherwise record a truthful skip.
- Record the exact commit and next bounded task (`MS5-IDENTITY-C`).
