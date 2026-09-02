# API_INVENTORY

Status: current candidate
Source: backend/app/api/v1 and generated OpenAPI
Date: 2026-09-02
Migration head: 20260902_0051

## Contract rules

- FastAPI OpenAPI is the only HTTP contract source.
- Frontend types are generated into frontend/src/shared/api/generated.ts.
- User-facing access is the frontend gateway at port 8080; the API process is
  an internal Compose service on port 8000.
- No compatibility endpoint is kept for retired product concepts.

## Route ownership

| Surface | Module | Current responsibility |
|---|---|---|
| Auth and workspaces | auth.py, workspaces.py | session, owner bootstrap, workspace CRUD |
| Projects | projects.py | POST/GET project shell |
| Script | scripts.py | script import, ScriptDocument/Episode/Scene/Shot reads, Shot canvas proposals |
| Assets | assets.py | Asset, AssetVersion, AssetVersionReference and tags |
| References | references.py | explicit ShotReferenceBinding CRUD and resolution |
| Scenes | scenes.py, workflow_overview.py | scene structure and read-only scene production view |
| Workbench | workbench.py | Shot design, execution-plan preview, execution dispatch, formal selection, trace, Review/Repair |
| Director Assistant | director.py, editing.py | read-only Shot suggestion and EditSession suggestion |
| Review | review.py | evidence annotations and decisions |
| Production monitor | production.py | Artifact bytes/frames, project snapshot, Outbox/Arq enqueue |
| Providers | provider_connections.py, provider_references.py, generations.py | model catalog, connection revisions, capability generation and reference delivery |
| Experiments | experiments.py | isolated Shot experiment branches and adoption |
| Editing | editing.py, opencut.py | EditSession timeline, suggestion, export, OpenCut manifest |
| Creative capabilities | creative_capabilities.py, workflow_planning.py | provider-neutral intent/capability planning only |

## Deliberately absent

The following route families are not present in the current OpenAPI:

- Quick project mode and Quick design preview;
- Creation Brief/Plan confirmation or Plan-to-media materialization;
- controlled Director workflow, budget, approval, trial, production-batch,
  repair-authorization, and old export commands;
- synchronous characters/lead registration;
- direct Shot start/rerun/approve/reject/lock/manual-media commands.

The replacements are explicit POST /projects, script import, AssetVersion and
ShotReferenceBinding, Workbench execution-plan/executions, Review/Repair,
Artifact delivery, and EditSession export.

## Required checks

npm run api:check
frontend: npm run format:check
backend: alembic check
backend: pytest tests/unit
backend: pytest tests/integration/test_s1_db_migration_pg.py

The authoritative dependency installation and command execution are defined by
docker-compose.quality.yml. The repository does not require a host Python or
Node installation for development or release evidence.
