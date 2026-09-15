# CREATION_FLOW — 唯一创作主链权威

Status: current / Date: 2026-09-14 / Base: dev 070faa3 / Alembic head: 20260910_0066
（入口见 [CURRENT.md](CURRENT.md)）

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
