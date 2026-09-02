# P10 C2 — Creation Compatibility Hard Removal

**Task:** `p10-c2-creation-hard-removal-20260902`
**Base:** `codex/cleanup-legacy-quick-media-20260902@a0ed4b9`
**Status:** IN PROGRESS

## Boundary

Remove the retired Creation start/state/brief/plan materialization surface and
the fixed-ten-shot/P0 Golden product entry points. Project creation remains a
small canonical `POST /projects` operation; Story drafting is a later task and
does not get invented here.

## Current evidence

- The project lobby now calls `POST /api/v1/projects` and no longer sends an
  initial idea into Creation state.
- The Creation router has been removed from API registration and its frontend
  API helpers/tests have been deleted.
- The generated frontend contract has been regenerated after removing the
  Creation router; remaining legacy paths belong to C3/C4/C5 cleanup slices.
- The old backend Creation service/models and P0 media helpers still have
  internal consumers and are removed only after those consumers are migrated or
  deleted in the following bounded slices.

## Required gate

- No executable product or test source exposes Creation start/state, Plan
  confirmation/materialization, P0 Golden, or fixed-ten-shot behavior.
- `POST /projects` creates only an empty canonical project and makes no Provider
  request.
- Canonical Scene/Shot/Workbench/Execution tests remain green.

## Explicitly out of scope

- New Story UI or Story Apply API.
- Historical data migration or rollback support.
- Provider behavior, automatic fallback, or database destructive migration;
  those are handled by C4/C6 with separate evidence.
