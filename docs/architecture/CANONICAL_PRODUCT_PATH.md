# CANONICAL_PRODUCT_PATH

Status: current
Date: 2026-09-14
Base: dev 63935b9
Alembic head: 20260910_0066
Owner program: DramaForge Professional 七方案 + Owner amendments

## Product chain

Project (Template Start / Free Start)
→ Story Proposal / Script Draft
→ ScriptDocument / Episode / Scene / Shot
→ AssetVersionReference / ProjectCreativeProfile
→ WorkbenchExecutionPlan
→ ProductionGraph → NodeRun → ProviderOperation → Artifact
→ Candidate / Formal → Review / Experiment / Repair
→ EditSession / Timeline → OpenCut editing → Final Film (MP4 + SRT) → Export.

There is one product path. Template / Free Start and AUTO / ASSIST / MANUAL only
affect initialization and Director behavior; they never create a second runtime
or change the Project, Scene/Shot, Candidate/Formal, Production Runtime,
Artifact lineage, or EditingAdapter semantics. Director autonomy never bypasses
the explicit Apply / Save / Formal / Export gates.

## Director runtime

Director orchestration is an independent runtime with one shared production
runtime:

- `DirectorTurn` / `DirectorInvocation` / `DirectorInbox` / `DirectorWakeup`
  persist bounded turn and text-invocation identity;
- `app/director/runtime` holds the engine ports, routing, projector, wakeups and
  the optional Python LangGraph adapter, with a project-scoped private
  checkpoint schema (migration `20260910_0066`);
- `app.workers.director` (`arq app.workers.director.WorkerSettings`) consumes the
  `dramaforge:director` queue.

`DIRECTOR_RUNTIME_ENGINE` defaults to `legacy`; `langgraph` is assigned only to
newly started turns and only when its hard gates are satisfied. Selecting one
engine never silently runs the other. Manual production must still complete with
the director worker stopped.

## Frontend routes

- `/` — Project Lobby and `POST /projects`;
- `/projects/$projectId` — project workspace shell (script / assets / scenes /
  production / review / edit entry points);
- `/projects/$projectId/script` — ScriptDocument import and read;
- `/projects/$projectId/assets` — Asset and AssetVersion management;
- `/projects/$projectId/scenes` and `/projects/$projectId/scenes/$sceneId` —
  Scene / Shot workbench;
- `/projects/$projectId/production` — monitor, capabilities, review and editing
  entry points;
- `/projects/$projectId/review` — review and repair workspace;
- `/projects/$projectId/edit` — EditSession timeline, suggestions and export;
- `/settings` with `/account`, `/workspaces`, `/models`, `/defaults` and
  `/projects/$projectId` — account, workspace, model connection, default
  preference and project settings;
- `/design-preview` — neutral design-system showcase.

Quick routes and Quick mock product routes are deleted. Server state lives in
TanStack Query; Zustand only holds layout/selection UI state.

## Execution ownership

The API only validates input, freezes model/reference identity, persists a
queued NodeRun, and publishes it through Outbox/Arq. Worker jobs call
`execute_media_node_run`:

keyframe/video → unified-v1 ProviderRuntime/compiler → Artifact
voice → explicit local-voice-v1 runtime → Artifact
review/subtitle/composite → zero-cost local node → Artifact

The shared execution module has no Director workflow, budget, batch, or
historical-path branch. Provider-specific reference URL/bytes decisions live
inside the provider delivery layer. Terminal shot notices are emitted atomically
from every status-writing path.

## Identity ownership

An identity asset is an Asset with one or more immutable AssetVersion rows.
References are explicit AssetVersionReference rows and are selected for a Shot
through ShotReferenceBinding. There is no character subtable, name guess,
prompt guess, or dual-read compatibility path.

## Assistant boundary

Director Assistant is proposal-only. Shot suggestions are non-persistent
responses; editing suggestions persist DirectorProposal/DirectorProposalItem and
are applied only through the typed command registry. Assistant rows never create
media or own execution state, and no route fabricates success when a trusted
evaluator is unavailable.

## Release and container rule

Runtime images are built from the same source SHA that is tested. The
authoritative quality gate is `docker-compose.quality.yml`:

- backend quality container: directory and canonical-surface scans, ruff, mypy,
  unit tests, PostgreSQL `alembic upgrade head` / `alembic check` and integration
  tests, OpenAPI export;
- frontend quality container: generated API check, format check, lint,
  typecheck, Vitest, production build, Playwright E2E;
- LiteLLM integration container: pinned official proxy image with deterministic
  mock models, no external Provider call.

Port 8080 is the only host-facing application entry (unprivileged Nginx
gateway). API port 8000 remains an internal container port behind the gateway.
