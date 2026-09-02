# CANONICAL_PRODUCT_PATH

Status: current candidate
Date: 2026-09-03
Base: dev 8ac3546
Alembic head: 20260902_0051
Owner goal: DramaForge V1 统一创作主链

## Product chain

Project (Template Start / Free Start)
→ Story Proposal / Script Draft
→ ScriptDocument / Episode / Scene / Shot
→ AssetVersionReference / ProjectCreativeProfile
→ WorkbenchExecutionPlan
→ ProductionGraph → NodeRun → ProviderOperation → Artifact
→ Candidate / Formal → Review / Experiment / Repair
→ EditSession / Timeline → OpenCut Director Editing → Export → Final Film.

There is one product path. Story proposals are intentionally out of scope for
this cleanup and are introduced by the V1 Story proposal Task Contract.
Template / Free Start and AUTO / ASSIST / MANUAL only affect initialization
and Director behavior; they never change the Project, Scene/Shot,
Candidate/Formal, Production Runtime, Artifact lineage, or EditingAdapter.

## Frontend routes

- / — project lobby and POST /projects;
- /projects/:projectId/script — ScriptDocument import/read;
- /projects/:projectId/assets — Asset and AssetVersion management;
- /projects/:projectId/scenes and /scenes/:sceneId — Scene/Shot workbench;
- /projects/:projectId/production — monitor, capabilities, review and editing
  entry points;
- /projects/:projectId/edit — EditSession timeline and export;
- /design-preview — neutral design-system showcase.

Quick routes and Quick mock product routes are deleted.

## Execution ownership

The API only validates input, freezes model/reference identity, persists a
queued NodeRun, and publishes it through Outbox/Arq. Worker jobs call
execute_media_node_run:

keyframe/video → unified-v1 ProviderRuntime/compiler → Artifact
voice → explicit local-voice-v1 runtime → Artifact
review/subtitle/composite → zero-cost local node → Artifact

The shared execution module has no Director workflow, budget, batch, or
historical-path branch. Provider-specific reference URL/bytes decisions live
inside the provider delivery layer.

## Identity ownership

An identity asset is an Asset with one or more immutable AssetVersion rows.
References are explicit AssetVersionReference rows and are selected for a Shot
through ShotReferenceBinding. There is no character subtable, name guess,
prompt guess, or dual-read compatibility path.

## Assistant boundary

Director Assistant is proposal-only. Shot suggestions are non-persistent
responses; editing suggestions persist DirectorProposal/DirectorProposalItem
and are applied only through the typed command registry. Assistant rows never
create media or own execution state.

## Release and container rule

Runtime images are built from the same source SHA that is tested. The
authoritative quality gate is docker-compose.quality.yml:

- backend quality container: locked Python 3.12 dependencies, ruff, unit tests,
  PostgreSQL migration/contract test, OpenAPI export;
- frontend quality container: locked Node 22 dependencies, generated API check,
  lint, typecheck, Vitest, and production build.

Port 8080 is the only host-facing application entry. API port 8000 remains an
internal container port behind the frontend gateway.
