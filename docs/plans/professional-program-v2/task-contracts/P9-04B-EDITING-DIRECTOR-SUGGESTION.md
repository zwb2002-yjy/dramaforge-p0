# Task: P9-04B — Editing Director Suggestion → Persisted Proposal Service

## Status

- **State:** COMPLETE
- **Program order:** P9-04A Typed EditSession Proposal Apply（已完成）→ **P9-04B Editing Director Suggestion → Persisted Proposal（本任务）** → 后续 P9-04 UI / approved model transport
- **Task id:** `p9-04b-editing-director-suggestion`
- **Task boundary:** Read the current server-owned `EditSession`, produce one
  strictly typed timeline suggestion through a deterministic no-network
  transport, and persist exactly one existing `DirectorProposal` with one
  `edit_session.apply_timeline_plan` command item.  The service never applies
  the proposal and never changes editing, production, execution, or provider
  facts.

## Read first

- [`../README.md`](../README.md) — authoritative seven-plan order
- [`P9-OPENCUT-EDITING.md`](P9-OPENCUT-EDITING.md) — DramaForge/OpenCut truth boundary
- [`P7-02-DIRECTOR-THREAD.md`](P7-02-DIRECTOR-THREAD.md) — allowed thread scopes
- [`P7-PROPOSAL-ORM-COMMANDS.md`](P7-PROPOSAL-ORM-COMMANDS.md) — existing proposal ORM and typed command registry
- [`P7-STALE-PANEL-GATE.md`](P7-STALE-PANEL-GATE.md) — stale proposal semantics
- [`P9-04A-EDITING-PROPOSAL-APPLY.md`](P9-04A-EDITING-PROPOSAL-APPLY.md) — strict timeline plan and versioned command
- [`../01-DramaForge_专业版产品与开发最终方案_完整交互版.md`](../01-DramaForge_专业版产品与开发最终方案_完整交互版.md) §80–§85 — editing and Director suggestion boundaries
- Existing `backend/app/editing/adapter.py`, `backend/app/editing/proposal_plan.py`, and `backend/app/director/proposal_commands.py`

## Current evidence / drift

- `EditSession` owns the persisted editable timeline and a positive optimistic
  `version`; `production_lineage` is readonly provenance.
- P9-04A already provides the canonical strict
  `EditSessionTimelinePlan` and the version-checked
  `edit_session.apply_timeline_plan` command.
- Existing `DirectorProposal` / `DirectorProposalItem` persistence and
  `DirectorThread` scope uniqueness are the only proposal seams to reuse.
- No approved model/LLM transport is authorized for this task.  The default
  transport must therefore be deterministic and no-network.

## Implementation contract

1. **Server truth and ownership.** Validate project ownership through the
   existing project service and load the session with both `project_id` and
   `session_id`.  The request accepts only `expected_session_version` and a
   non-blank `user_instruction`; timeline, lineage, artifact, provider,
   runtime, worker, execution, and SQL fields are never client-controlled.
2. **Two stale gates.** Before invoking the transport, require the server
   session version to equal the request's expected version.  After transport
   output validation and target validation, re-read the session and require
   the same version.  A stale request/output persists no proposal or item.
3. **Safe transport seam.** Resolve a deterministic local transport by default;
   it may only suggest operations against existing clip ids.  There is no HTTP
   client, provider dispatch, AgentRun, ProviderOperation, Worker, or billing
   path in this task.
4. **Strict typed plan reuse.** Validate transport output through the existing
   `EditSessionTimelinePlan` model.  Only exact existing-clip permutations and
   finite non-negative durations are accepted.  Reject unknown fields and
   recursively reject artifact/provider/runtime/execution/NodeRun/Worker/raw
   replacement/JSON Patch/SQL/path/production-lineage payloads.
5. **Proposal persistence only.** Reuse or create exactly one
   `DirectorThread` with `scope_type="project"` and
   `scope_entity_id=project.id`.  Persist one `DirectorProposal` scoped to the
   target EditSession and one pending
   `DirectorProposalItem` whose command is exactly
   `edit_session.apply_timeline_plan` and whose
   `expected_target_version` exactly equals the server version read by both
   stale gates.  Do not call `ProposalCommandRegistry.apply`.
6. **Fact preservation.** Suggestion generation changes neither
   `EditSession.timeline` nor `EditSession.production_lineage`, and does not
   mutate Shot, Asset, ProductionGraph, NodeRun, Artifact, ProviderOperation,
   or any execution/provider/runtime fact.  Applying a proposal remains a
   separate explicit user action through P9-04A.

## Explicitly out of scope

- HTTP routes, frontend/UI wiring, OpenCut changes, autosave, or automatic
  proposal acceptance/application.
- LLM/model/provider calls, network access, AgentRun, ProviderOperation,
  Worker, Runtime, billing, or execution dispatch.
- A new proposal table, thread model, timeline model, JSON Patch format, raw
  SQL, arbitrary table/column writes, or a second production/timeline truth.
- Mutating production lineage, formal Shot/Asset facts, ProductionGraph,
  NodeRun, Artifact, or provider execution records.

## Owned paths

- `backend/app/director/editing_suggestion.py`
- `backend/tests/unit/test_editing_director_suggestion.py`
- `docs/plans/professional-program-v2/task-contracts/P9-04B-EDITING-DIRECTOR-SUGGESTION.md`

## Verification gate

- Focused unit tests cover server-fact context isolation, project/session
  ownership, stale-before-transport and stale-after-re-read zero proposal
  persistence, deterministic default behavior, strict plan/target validation,
  recursive forbidden-field attacks, exact proposal/item payload and version,
  project-thread reuse, no apply, and unchanged editing/production/execution
  facts.
- `ruff check app tests` and `mypy app` pass for the focused implementation;
  existing P9-04A proposal-command tests remain green.
- `git diff --check` is clean.  No branch, commit, push, or provider/network
  operation is part of this task.
