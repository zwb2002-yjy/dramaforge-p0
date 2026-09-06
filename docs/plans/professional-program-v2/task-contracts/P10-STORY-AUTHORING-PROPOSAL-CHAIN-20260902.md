# P10 Story Authoring Proposal Chain

**Task:** `p10-story-authoring-proposal-chain-20260902`
**Status:** READY / NOT STARTED
**Parent:** P10 hard-removal completion

## Boundary

This contract begins only after the P10 C0–C7 hard-removal gates are green. It
defines the next bounded Story task; it does not reopen the retired Creation,
Quick, controlled Director, Budget, Batch, or fixed-shot surfaces.

## Outcome

Add one proposal-first authoring chain:

```text
Idea
→ Creative Brief Proposal
→ Story Direction Proposal
→ Script Draft
→ Structure Diff
→ User Preview / Partial Accept
→ ScriptDocument / Episode / Scene / Shot
```

The applied ScriptDocument/Episode/Scene/Shot graph is the only canonical
story fact. A draft or proposal is never a second story database and does not
generate media.

## Required invariants

- Proposal creation is non-destructive and idempotent.
- Preview exposes the exact pending diff before apply.
- Partial accept applies only the explicitly accepted operations.
- Stale proposals fail closed against the current canonical version.
- Apply writes canonical Story rows once and emits no Provider request.
- Scene/Shot Workbench is the only entry point for later media execution.
- Shot count is derived from the accepted story structure; no fixed cardinality
  is introduced.

## Explicitly out of scope

- Story UI implementation in this cleanup task;
- a second Script/Scene/Shot truth source;
- media generation during authoring;
- automatic model routing, budget authorization, or compatibility aliases;
- restoring any removed P10 surface.

## Required evidence before completion

- a separate schema/API design review for proposal and diff persistence;
- backend unit and PostgreSQL tests for idempotency, stale rejection, partial
  apply, canonical graph writes, and zero Provider requests;
- frontend contract, unit, and Playwright coverage for preview/apply/reject;
- generated OpenAPI and architecture inventory updates;
- the existing P10 canonical surface, migration, and Workbench gates remain
  green.
