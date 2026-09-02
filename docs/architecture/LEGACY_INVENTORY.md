# LEGACY_INVENTORY

Status: hard-removal completed in the current candidate
Date: 2026-09-02
Contract: docs/plans/professional-program-v2/task-contracts/P10-LEGACY-HARD-REMOVAL-20260902.md

## Removed from executable product

| Retired area | Removal evidence |
|---|---|
| Quick route, mode, mock, navigation, and tests | no Quick route/module or mode enum remains |
| Creation Brief/Plan/Authorization/Materialize package | backend/app/creation and creation router deleted |
| Fixed-ten-shot P0 path and fixture | old P0 materializer, fake first-frame pipeline and ten-shot fixture deleted |
| Controlled Director workflow | workflow, budget, approval, trial, batch, repair and old export services/routes deleted |
| Direct Shot action API | shot action router deleted; Workbench execution and Review/Repair remain |
| Character/CharacterReference compatibility layer | generic AssetVersionReference is the only identity reference source |
| Runtime split and migration switch flags | keyframe/video always enter unified-v1; obsolete flags removed |
| G4 legacy evidence drivers | old Director/P0 evidence scripts deleted or replaced by canonical proof scripts |

## Canonical modules that remain

- backend/app/director/suggestion.py for non-persistent Shot suggestions;
- backend/app/director/assistant_models.py and proposal_models.py for
  proposal-only Assistant facts;
- backend/app/director/creative_capabilities and the provider-neutral workflow
  definitions used by the Workbench;
- backend/app/production/workbench_execution.py,
  backend/app/execution/product_path.py, and backend/app/execution/voice_path.py;
- backend/app/assets/models.py Asset/AssetVersion/AssetVersionReference;
- backend/app/production/repair_service.py and editing services.

## Database evidence

Migration 20260902_0051 drops retired tables, identity tables, the mode/guide
columns, NodeRun budget/batch columns, and ProviderOperation AgentRun lineage.
It also replaces the provider-operation RLS policy/function before dropping the
old column. The migration is intentionally irreversible because the Owner
withdrew historical compatibility and rollback requirements.

## Gate

The repository must fail if a retired route/module identifier is reintroduced.
The source scan, model-registry test, generated OpenAPI check, PostgreSQL
migration check, and container quality gate enforce this boundary.
