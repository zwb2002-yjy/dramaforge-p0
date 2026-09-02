# P10 Legacy Hard Removal — Owner Revision 2026-09-02

**Status:** COMPLETE
**Base:** `dev@e8da0da167624aed944a7b5c4a42e4f56a65fb02`  
**Branch:** `codex/cleanup-legacy-quick-media-20260902`  
**Canonical chain protected:** Project → ScriptDocument → Episode → Scene → Shot → ProductionGraph → NodeRun → ProviderOperation → Artifact

## Owner revision

On 2026-09-02 the Owner explicitly withdrew the prior compatibility and rollback requirement:

- historical Quick projects do not need a recovery path;
- old Quick / controlled Director / budget / batch compatibility should be removed before new Story work;
- fixed ten-shot assumptions must not remain in product behavior;
- historical legacy data does not need to be migrated;
- repository cleanliness takes precedence over preserving retired API/UI contracts.

This bounded revision supersedes the prior P10-01 instruction to retain `/quick` and the transition-only instruction not to delete Legacy logic. It does not change the seven original source files or their integrity hashes.

## Current evidence

At the base SHA:

- `/projects/$projectId/quick` is a retire notice but remains registered.
- `backend/app/api/v1/creation.py` remains mounted and exposes legacy Plan media materialization.
- `CreationService.generate_plan_agent` prompts for exactly ten shots and `_parse_plan_json` rejects every other count.
- the old controlled Director router still exposes workflow, budget, trial, production, repair and export commands.
- eleven legacy Director tables remain; `NodeRun` still has batch/budget foreign keys.
- legacy project export and P0 Golden HTTP endpoints remain mounted.
- the professional Scene/Shot path does not require Quick, old Budget authorization or old Director workflow.
- the canonical real-provider proof script uses professional APIs and one Shot; it does not require the ten-shot P0 endpoint.

The C0 consumer/deletion matrix is recorded in
[`P10-C0-LEGACY-CONSUMER-MATRIX-20260902.md`](P10-C0-LEGACY-CONSUMER-MATRIX-20260902.md).
It names the current consumers, canonical replacements, and removal stage for
each retired surface before implementation proceeds.

## Required outcome

After this task:

1. no product or design-preview route contains Quick mode;
2. no API provides legacy Plan-to-media materialization or P0 Golden production;
3. no product code requires exactly ten shots;
4. no API exposes old controlled Director workflow, budget, trial, production-batch or repair authorization;
5. no new execution branches on historical Director/Batch presence;
6. old Director/Creation compatibility tables and NodeRun legacy foreign keys are dropped by Alembic;
7. unified model resolution and the Professional Worker path are the only media execution path;
8. Director Shot suggestions, typed proposals, Scene/Shot generation, Review/Repair and EditSession remain;
9. generated OpenAPI, tests and architecture inventories match the reduced surface;
10. CI, PostgreSQL migration, API contract and professional E2E gates pass.

## Work slices

### L1 — Product surface removal

Delete Quick route/mock assets, old stage UI, orphan tests and navigation special cases.

### L2 — Creation compatibility removal

Retain only text/story draft facts needed for the upcoming Story task. Remove Plan media materialization, fixed-ten validation/prompts, recovery mode and old Golden/Project export entry points.

### L3 — Controlled Director removal

Reduce the Director API to current proposal-only Shot assistance. Remove workflow/budget/trial/production/repair services and frontend consumers that depend on the retired fact model.

### L4 — Runtime and schema convergence

Remove Director/Batch branching from media execution, remove NodeRun legacy foreign keys, drop retired tables/enums and make the unified execution path the sole path.

### L5 — Contract and evidence cleanup

Regenerate OpenAPI, remove obsolete tests/fixtures/scripts, refresh Legacy/API/Canonical inventories and run all gates.

## Out of scope

- new Story UI or Story Apply API;
- Production page redesign beyond removing retired calls;
- team permissions;
- cost/budget replacement;
- automatic model fallback;
- destructive deletion of canonical projects, Shots, Artifacts or ProviderOperations.

## Gates

- no source hit for retired route/endpoint identifiers except this contract and historical evidence;
- no source hit for `exactly 10` or `p0_10_shots` in executable product/test code;
- Alembic upgrade from current head succeeds on PostgreSQL;
- backend unit/integration, frontend unit/type/build/E2E and security gates pass;
- professional one-Shot real-provider script remains structurally intact; paid execution requires separate Owner authorization.

## Completion evidence

The continuation branch now satisfies the required outcome on the current
candidate: the canonical surface scan and directory compliance scan pass;
backend static checks, 872 unit tests, PostgreSQL migration/integration checks,
and OpenAPI export pass; frontend format, lint, typecheck, 101 unit tests,
production build, and 13 Playwright tests pass. The Docker quality images run
these checks from the repository source context and preserve the generated
OpenAPI contract for the frontend gate.
