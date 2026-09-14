# CODE_OWNERSHIP_MATRIX

Status: current
Date: 2026-09-14
Base: dev 63935b9

| Domain | Source of truth | May own | Must not own |
|---|---|---|---|
| Access | backend/app/access | users, workspaces, projects, workspace state and creative profile | media execution or provider selection |
| Story/Assets | backend/app/assets | ScriptDocument, Episode, Scene, Shot, Asset, AssetVersion, version references, tags | provider calls |
| References | backend/app/production/reference_intents.py and api/v1/references.py | explicit binding, compilation, model capability gaps | name/prompt fallback |
| Workbench | backend/app/workbench and backend/app/production/workbench_execution.py | workspace state, frozen execution plan and NodeRun creation | direct Provider HTTP, budget gate |
| Production graph | backend/app/production | graph versions, branches, formal selection, repair plans, Final Film and timeline rendering | HTTP/API concerns, silent rerun |
| Runtime | backend/app/execution/product_path.py and voice_path.py | Worker execution, lineage, artifact persistence, shot locks | HTTP/API concerns, old branches |
| Director Assistant | backend/app/director/assistant_models.py, suggestion.py, proposal_* | suggestions, threads, typed proposal/apply boundary | media, budgets, workflow ownership |
| Director runtime | backend/app/director/runtime and backend/app/workers/director.py | turn/invocation identity, engine routing, checkpoints, wakeups, resume fencing | Canonical media writes or bypassing Apply/Save/Formal gates |
| Providers | backend/app/providers | manifests, compilers, runtime adapters, connection/credential revisions, model profiles | product stages or UI state |
| Review/Repair | backend/app/delivery and backend/app/production/repair_service.py | annotations, decisions, explicit repair plans | silent rerun or fallback |
| Editing | backend/app/editing, api/v1/editing.py, api/v1/opencut.py | EditSession timeline, suggestions and export | rewriting production truth |
| Events | backend/app/events and backend/app/workers/dispatcher.py | event log, outbox delivery, dead letters, SSE | product decisions |
| Security | backend/app/security | encrypted BYOK credentials and rotation audits | credential readback |
| Contracts | backend/app/contracts | shared typed runtime/production command and fact contracts | persistence or HTTP surface |
| Workers | backend/app/workers | Arq default/director/heavy entry points and recovery ticks | domain rules owned by other packages |
| Frontend | frontend/src/routes and frontend/src/features | views and explicit user commands | duplicated server truth |

## Dependency direction

UI → typed API client → domain service → canonical models/runtime.
Provider adapters are reached only by Workbench Worker execution or their
explicit configuration/probe boundary. All source commits must pass the
container quality gate and the generated OpenAPI check.

## Removed ownership areas

Creation package, controlled Director workflow services, batch/budget facts,
Quick mode, Character/CharacterReference compatibility, direct Shot action
router, and runtime switch flags are no longer owned by any source module.
`scripts/check_canonical_surface.py` fails the gate if they are reintroduced.
