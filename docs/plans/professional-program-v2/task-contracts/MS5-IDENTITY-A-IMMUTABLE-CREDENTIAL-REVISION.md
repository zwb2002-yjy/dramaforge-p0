# Task: MS5-IDENTITY-A — Immutable Credential Revision

## Status

- **State:** IN PROGRESS
- **Program order:** `MS5-R` → `MS5-IDENTITY-A` → `MS5-IDENTITY-B` → `MS5-IDENTITY-C` → Phase 4 Merge Gate
- **Task boundary:** Implement only immutable credential revisions and the strict credential-id read path. Do not implement `ProviderConnectionRevision`, `ExecutionIdentitySnapshot`, resume reconstruction, or Phase 4 merge work in this contract.

## Read first

- [`../README.md`](../README.md)
- [`../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md`](../06-DRAMAFORGE_PRO_REVIEW_REVISED_DESIGN.md) §§8.1–8.2
- [`../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md`](../07-DRAMAFORGE_PRO_REVIEW_REVISED_IMPLEMENTATION_PLAN.md) §12
- Current `backend/app/security/models.py`, `backend/app/security/credentials.py`, `backend/app/providers/workspace_credentials.py`, and provider connection service
- Existing BYOK migrations and credential/connection tests

## Current evidence / drift

- `EncryptedProviderCredential` currently enforces `UNIQUE(workspace_id, provider)` and permits in-place mutation of `ciphertext` and `key_version`.
- `store_credential()` currently queries by `(workspace_id, provider)` and updates that row when one exists.
- `read_credential()` and `runtime_connection_settings()` can resolve by `(workspace_id, provider)` instead of the concrete `ProviderConnection.credential_id`.
- `ProviderConnection` already stores a credential foreign key, but the Professional runtime read path is not yet strict by that identity.
- `key_version` is encryption/keyring metadata; it must not be conflated with an account credential revision.

## Objective

Make each account credential update produce an immutable revision record while preserving old rows and making the Professional connection path consume the concrete credential revision named by `connection.credential_id`.

## Required behavior

1. **Schema / migration**
   - Add `revision_no` and nullable `supersedes_id` to `encrypted_provider_credentials`.
   - Remove `UNIQUE(workspace_id, provider)` while retaining all existing rows.
   - Backfill existing rows deterministically as revision 1 with no predecessor (or an equivalent explicit baseline that preserves their identity).
   - Add database constraints/indexes needed to prevent duplicate revision numbers per workspace/provider and to validate predecessor workspace/provider ownership.
2. **Immutable service semantics**
   - `store_credential()` always INSERTs a new row; it never overwrites an existing ciphertext/key version.
   - New rows increment the workspace/provider revision and point `supersedes_id` at the previous latest row.
   - Add `read_credential_by_id(workspace_id, credential_id, keyring)` and enforce workspace ownership in the query.
   - Keep `read_credential()` / `has_credential()` only as explicitly documented legacy provider-key compatibility helpers; Professional paths must not use them for a concrete connection.
   - `rotate_credentials()` must remain key rotation: it may re-encrypt ciphertext/key_version in place for the same revision and must not create account revisions or change `revision_no` / `supersedes_id`.
3. **Professional connection path**
   - `runtime_connection_settings()` and the provider connection service’s concrete settings path must read the credential referenced by `connection.credential_id` through the strict helper.
   - A missing or cross-workspace credential must fail closed without exposing secret material.
4. **Security / response boundary**
   - Existing API responses and snapshots must not include plaintext, ciphertext, or API-key fragments.
   - Old account revisions must remain decryptable after a credential update and after key rotation when the corresponding key versions are available.

## Owned paths

- `backend/app/security/models.py`
- `backend/app/security/credentials.py`
- `backend/app/providers/workspace_credentials.py`
- `backend/app/providers/connection_service.py`
- `backend/alembic/versions/20260826_0041_immutable_credential_revisions.py`
- `backend/tests/unit/test_workspace_byok.py`
- `backend/tests/unit/test_rotate_byok_keys.py`
- `backend/tests/unit/test_provider_connections.py`
- `backend/tests/unit/test_credential_revisions.py`
- `docs/plans/professional-program-v2/task-contracts/MS5-IDENTITY-A-IMMUTABLE-CREDENTIAL-REVISION.md`
- `docs/开发执行检查点.md`

## Explicitly out of scope

- `ProviderConnectionRevision` table or operation linkage (MS5-IDENTITY-B).
- `ExecutionIdentitySnapshot`, worker restart/resume/poll/cancel reconstruction (MS5-IDENTITY-C).
- New runtime/worker/generation abstractions, real Provider calls, paid Provider traffic, or unrelated schema cleanup.

## Verification gate

- Focused credential revision, workspace BYOK, rotation, and provider connection tests pass.
- Existing backend unit suite passes with no secret leakage regressions.
- `ruff check app tests alembic/versions` and `mypy app` pass.
- Migration chain compiles and the new migration has a reversible downgrade.
- PostgreSQL integration is run only if the configured database is reachable; otherwise the result is recorded as skipped, never as passed.
- `git diff --check` passes and no owned-path or plan-order guardrail fails.

## Completion evidence to record

- Migration name and schema constraints.
- Exact tests and static checks run, including any truthful PostgreSQL skip reason.
- Proof that two account updates retain two decryptable rows and that concrete connection lookup selects the referenced revision rather than the provider’s latest default.
- Commit SHA on `dev` and the next bounded task (`MS5-IDENTITY-B`).
