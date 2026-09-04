# CODE_OWNERSHIP_MATRIX

Status: current candidate
Date: 2026-09-02

| Domain | Source of truth | May own | Must not own |
|---|---|---|---|
| Access | backend/app/access | users, workspaces, projects and workspace state | media execution or provider selection |
| Story/Assets | backend/app/assets | ScriptDocument, Episode, Scene, Shot, Asset, AssetVersion, version references | provider calls |
| References | backend/app/production/reference_intents.py and api/v1/references.py | explicit binding, compilation, model capability gaps | name/prompt fallback |
| Workbench | backend/app/production/workbench_execution.py | frozen execution plan and NodeRun creation | direct Provider HTTP, budget gate |
| Runtime | backend/app/execution/product_path.py and voice_path.py | Worker execution, lineage, artifact persistence | HTTP/API concerns, old branches |
| Providers | backend/app/providers | manifests, compilers, runtime adapters, connection revisions | product stages or UI state |
| Assistant | backend/app/director/assistant_models.py, suggestion.py, proposal_* | suggestions, threads, typed proposal/apply boundary | media, budgets, workflow ownership |
| Review/Repair | backend/app/delivery, backend/app/production/repair_service.py | annotations, decisions, explicit repair plans | silent rerun or fallback |
| Editing | backend/app/editing and api/v1/editing.py | EditSession timeline and export | rewriting production truth |
| Frontend | frontend/src/routes and frontend/src/features | views and explicit user commands | duplicated server truth |

## Dependency direction

UI → typed API client → domain service → canonical models/runtime.
Provider adapters are reached only by Workbench Worker execution or their
explicit configuration/probe boundary. All source commits must pass the
container quality gate and generated OpenAPI check.

## Removed ownership areas

Creation package, controlled Director workflow services, batch/budget facts,
Quick mode, Character/CharacterReference compatibility, direct Shot action
router, and runtime switch flags are no longer owned by any source module.
