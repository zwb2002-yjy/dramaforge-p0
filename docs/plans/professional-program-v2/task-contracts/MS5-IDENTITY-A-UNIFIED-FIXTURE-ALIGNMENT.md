# Task: MS5-IDENTITY-A — Unified Fixture Identity Alignment

## Status

- **State:** COMPLETE
- **Parent bounded task:** `MS5-IDENTITY-A-IMMUTABLE-CREDENTIAL-REVISION`
- **Purpose:** Align the existing unified-path unit fixture with the new strict credential identity contract. This is test-only support for MS5-IDENTITY-A; it does not introduce a second implementation task or change production behavior.

## Current drift

`backend/tests/unit/test_unified_path.py` stores a fake provider credential and then constructs its `ProviderConnection` with an unrelated `uuid4()` as `credential_id`. The new Professional runtime contract must resolve the concrete credential named by the connection and must not fall back to `(workspace, provider)` lookup, so the fixture no longer represents a valid connection.

## Required change

- Capture the credential returned by `store_credential()`.
- Set the fixture connection's `credential_id` and `credential_revision` from that concrete record.
- Preserve all existing unified-path assertions and fake-provider behavior.
- Do not weaken `runtime_connection_settings()` or add provider-key fallback.

## Owned paths

- `backend/tests/unit/test_unified_path.py`
- `docs/plans/professional-program-v2/task-contracts/MS5-IDENTITY-A-UNIFIED-FIXTURE-ALIGNMENT.md`

## Verification

- The full `test_unified_path.py` module passes without real Provider traffic.
- The changed fixture contains no secrets in snapshots or responses.
- `git diff --check` passes.
