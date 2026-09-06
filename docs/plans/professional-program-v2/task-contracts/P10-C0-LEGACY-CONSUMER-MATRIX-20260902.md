# P10 C0 — Legacy Consumer and Deletion Matrix

**Task:** `p10-c0-legacy-consumer-matrix-20260902`
**Base:** `dev@e8da0da167624aed944a7b5c4a42e4f56a65fb02`
**Continuation branch:** `codex/cleanup-legacy-quick-media-20260902`
**Status:** COMPLETE — consumer matrix recorded before hard removal

This matrix is the C0 deletion contract for the Owner-authorized hard-removal
revision. It records the current consumer boundary, the canonical replacement,
and the first removal stage. Historical evidence may mention these symbols,
but executable source and current API/OpenAPI evidence must satisfy the gates in
`P10-LEGACY-HARD-REMOVAL-20260902.md` after the corresponding stage.

| Retired surface | Current consumers at base | Canonical replacement | Removal stage |
|---|---|---|---|
| Quick route and mode | `frontend/src/routes/projects.$projectId.quick.tsx`, `WorkstationShell`, route tree, Quick mock tests/assets | Project shell with `/script`, `/scenes`, or last canonical location | C1 |
| Quick design preview | `frontend/src/routes/design-preview.tsx`, `creation-preview/*`, demo media and visual snapshots | Neutral shared design-system preview | C1 |
| Creation start/state API | `backend/app/api/v1/creation.py`, `frontend/src/lib/api.ts`, `frontend/src/shared/api/generated.ts`, creation/legacy-gate tests | `POST /api/v1/projects` plus Script Import and canonical Scene/Shot APIs | C2 |
| Plan confirm/materialize | `CreationService.confirm_plan_and_materialize`, `execution/product_path.py`, P0/Phase 3/4 fixtures and tests | Workbench `ExecutionPlan` → `ProductionGraph` → `NodeRun` | C2 |
| Fixed ten-shot contract | Agent-plan prompts/parser, `golden_path.py`, `p0_10_shots.md`, P0 and story-loop tests/scripts | User-selected ScriptDocument → Episode → Scene → Shot structure | C2 |
| P0 Golden HTTP and old export | `production.py`, `frontend/src/lib/api.ts`, P0 proof scripts, generated API types | Professional one-Shot proof and canonical Artifact/Edit export | C2/C7 |
| Controlled Director workflow | `director.py`, `director/service.py`, workflow services, workflow overview/planning APIs, old Director UI | Director Thread/Message, Shot Suggestion, Proposal/ProposalItem | C3 |
| Budget/Approval/Batch/Trial/Repair chain | Director and production services/schemas, `NodeRun` batch/budget fields, related tests and generated types | Explicit user save/apply plus canonical Workbench execution and Review/Repair | C3/C4/C6 |
| Legacy execution guards and path split | `director/legacy_guard.py`, `execution/product_path.py`, `shot_ops.py`, `generations.py`, Feature Flag fallback | One frozen ModelBinding/Manifest/Compiler/Worker path | C4 |
| Character lead and CharacterReference compatibility | `api/v1/characters.py`, `golden_project.py`, product path reference lookup, reference tests | `Asset` → `AssetVersion` → `AssetVersionReference` → `ShotReferenceBinding` | C5/C6 |
| Legacy ORM tables/enums and foreign keys | `creation/models.py`, `director/models.py`, `director/proposal_models.py`, `execution/models.py`, Alembic metadata/migrations, generated API schemas | Canonical Project/Scene/Shot/Execution/Review/Edit tables only | C6/C7 |

## Evidence commands

The base scan was performed with symbol and route searches across:

- `backend/app`, `backend/alembic`, `frontend/src`, `backend/tests`,
  `frontend/tests`, and `scripts`;
- API router registration and generated OpenAPI paths;
- ORM model declarations and `NodeRun` foreign-key fields;
- current frontend route tree and API helper consumers.

Every row has a named current consumer, a named canonical replacement, and an
assigned removal stage. No deletion target is left with an `unknown` consumer.

## Boundary

This matrix does not authorize new Story UI/API work, budget replacement,
automatic model fallback, or deletion of canonical Project, Shot, Artifact, or
ProviderOperation facts. It authorizes only the staged hard removal described by
the parent contract.
