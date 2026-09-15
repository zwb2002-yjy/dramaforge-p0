# API — HTTP 表面权威

Status: current
Source: backend/app/api/v1 and generated OpenAPI
Date: 2026-09-14
Base: dev 070faa3
Migration head: 20260910_0066
（入口见 [CURRENT.md](CURRENT.md)）

## Contract rules

- FastAPI OpenAPI is the only HTTP contract source.
- Frontend types are generated into frontend/src/shared/api/generated.ts.
- User-facing access is the frontend gateway at port 8080; the API process is
  an internal Compose service on port 8000.
- No compatibility endpoint is kept for retired product concepts.
- `backend/app/api/v1/router.py` registers 26 routers and exposes `/status`.

## Route ownership

| Surface | Module | Current responsibility |
|---|---|---|
| Auth and workspaces | auth.py | session, CSRF, owner bootstrap, workspace CRUD |
| Projects | projects.py | project shell and V1 CreativeTemplate profile |
| Script | scripts.py | script import, ScriptDocument/Episode/Scene/Shot reads, Shot canvas proposals |
| Story | story.py | proposal-first Story authoring: generate, preview and partial apply through the shared command registry |
| Assets | assets.py | Asset, AssetVersion, AssetVersionReference, asset cards and tags |
| References | references.py | explicit ShotReferenceBinding CRUD and `@Asset` resolution |
| Scenes | scenes.py, workflow_overview.py | scene structure, workspace snapshot, structural commands, read-only project workflow view |
| Workbench | workbench.py | workspace state, Shot design, execution-plan preview, execution dispatch, formal selection, trace, Review/Repair |
| Director Assistant | director.py | proposal-only Shot suggestion, bounded Director turns, runtime start/control/resume signals |
| Director board | director_board.py | per-shot 2D and rough-3D director board state |
| Review | review.py | evidence annotations and decisions |
| Production monitor | production.py | Artifact bytes/frames, project snapshot, Outbox/Arq enqueue |
| Providers | provider_connections.py, provider_references.py, credentials.py, generations.py, model_profiles.py, model_candidates.py | model catalog, connection/credential revisions, capability probe and generation, reference delivery, model profiles and read-only candidates |
| Experiments | experiments.py | isolated Shot experiment branches and adoption |
| Editing | editing.py, opencut.py, final_film.py | EditSession timeline, suggestion, export, OpenCut manifest, Final Film bound to a timeline version |
| Creative capabilities | creative_capabilities.py, workflow_planning.py | provider-neutral intent/capability planning and workflow-state freeze |
| Events | events.py | SSE subscription with Last-Event-ID resume |
| Worker tick | worker.py | worker-only HTTP tick for local/dev when Arq runs separately |

## Deliberately absent

The following route families are not present in the current OpenAPI:

- Quick project mode and Quick design preview;
- Creation Brief/Plan confirmation or Plan-to-media materialization;
- controlled Director workflow, budget, approval, trial, production-batch,
  repair-authorization, and old export commands;
- synchronous characters/lead registration;
- direct Shot start/rerun/approve/reject/lock/manual-media commands.

The replacements are explicit POST /projects, Story proposals, script import,
AssetVersion and ShotReferenceBinding, Workbench execution-plan/executions,
Review/Repair, Artifact delivery, and EditSession export.

## Required checks

npm run api:check
frontend: npm run format:check
backend: alembic check
backend: pytest tests/unit
backend: pytest tests/integration

The authoritative dependency installation and command execution are defined by
docker-compose.quality.yml (backend/Dockerfile.quality and
frontend/Dockerfile.quality). The repository does not require a host Python or
Node installation for development or release evidence.
