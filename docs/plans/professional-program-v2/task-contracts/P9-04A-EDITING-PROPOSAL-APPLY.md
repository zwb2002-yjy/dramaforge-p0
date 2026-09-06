# Task: P9-04A — Typed EditSession Proposal Apply

## Status

- **State:** COMPLETE
- **Program order:** P9-03B Editing Workspace Session UI（已完成）→ **P9-04A Typed EditSession Proposal Apply（本任务）** → 后续 P9-04 Director editing suggestions
- **Task id:** `p9-04a-editing-proposal-apply`
- **Task boundary:** Give `EditSession` a stable optimistic version and add
  one canonical Director proposal command for typed timeline operations.  This
  task does not add an LLM, Agent/UI, proposal table, or second timeline truth.

## Read first

- [`../README.md`](../README.md) 唯一顺序
- [`P9-OPENCUT-EDITING.md`](P9-OPENCUT-EDITING.md) Phase 9 boundary
- [`P7-PROPOSAL-ORM-COMMANDS.md`](P7-PROPOSAL-ORM-COMMANDS.md) typed command registry
- [`P7-STALE-PANEL-GATE.md`](P7-STALE-PANEL-GATE.md) stale item semantics
- [`P9-03A-EDITING-SESSION-HTTP.md`](P9-03A-EDITING-SESSION-HTTP.md)
- Existing `backend/app/editing/adapter.py` and `backend/app/director/proposal_commands.py`

## Current evidence / drift

- `EditSession` persisted `timeline` and read-only `production_lineage`, but
  had no optimistic version and no typed proposal command.
- Existing `EditingAdapter.save_timeline` and P7 `ProposalCommandRegistry` are
  the canonical seams; proposal application must use them without touching
  production facts.

## Implementation

- Add `EditSession.version` (positive, non-null, backfilled to `1`) via
  reversible migration `20260901_0050`.
- Manual adapter saves and the typed proposal command each increment version
  exactly once; production lineage remains unchanged.
- `EditSessionTimelinePlan` is strict and supports only:
  - `reorder_clips`: exact permutation of existing clip ids, with `order`
    updated while all other fields remain intact;
  - `set_clip_duration`: existing clip id and finite duration `>= 0`.
- The canonical `edit_session.apply_timeline_plan` command validates project,
  session and expected version, applies to a deep copy, and fails closed on
  production lineage, JSON Patch, arbitrary paths, provider/runtime/execution,
  SQL, raw replacement, malformed operation, or non-finite input fields.
- `ProposalService` marks only command failures carrying
  `details.code=PROPOSAL_STALE` as stale with `decided_at`; other partial-apply
  failures retain their existing behavior.

## Explicitly out of scope

- LLM/Agent generation, Director UI, P9-04 suggestion UX, or frontend changes
  other than generated API types for `version`.
- Proposal ORM/table/migration changes, JSON Patch, arbitrary writes, media
  execution, Provider/Runtime/Worker, Shot/Asset/ProductionGraph/NodeRun/
  Artifact/ProviderOperation mutations.

## Owned paths

- `backend/app/editing/models.py`
- `backend/app/editing/adapter.py`
- `backend/app/editing/proposal_plan.py`
- `backend/alembic/versions/20260901_0050_edit_session_version.py`
- `backend/app/api/v1/editing.py`
- `backend/app/director/proposal_commands.py`
- `backend/app/director/proposal_service.py`
- `backend/tests/unit/test_editing_proposal_commands.py`
- `frontend/src/shared/api/generated.ts` (generated only)
- `docs/plans/professional-program-v2/task-contracts/P9-04A-EDITING-PROPOSAL-APPLY.md`

## Verification gate

- Focused tests cover version transitions, valid reorder/duration apply, exact
  permutation, strict malformed-plan rejection, stale zero-mutation plus stale
  item status, rejection zero-mutation, cross-project isolation, lineage
  preservation, and unchanged production/execution facts.
- Existing proposal, stale-panel, EditingAdapter gate, Editing API, schema,
  and metadata tests remain green.
- `ruff`, `mypy app`, offline Alembic upgrade SQL, frontend generated API
  generation/check, and `git diff --check` pass.
