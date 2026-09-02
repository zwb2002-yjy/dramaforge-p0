# PHASE_GATE

Status: P10 hard-removal candidate
Date: 2026-09-02
Base: dev e8da0da

## Completed cleanup gates

| Gate | Evidence |
|---|---|
| C0 consumer matrix | P10-C0-LEGACY-CONSUMER-MATRIX-20260902.md |
| C1 Quick/frontend cleanup | Quick route, mock, navigation, old Stage UI and orphan tests deleted |
| C2 Creation cleanup | Creation router/service, Plan materialization, fixed-ten fixture and old export/Golden entry points deleted |
| C3 Director convergence | only Shot suggestion remains in Director API; thread/proposal models are isolated |
| C4 runtime convergence | keyframe/video always use unified-v1; local voice has a named neutral path; switch flags removed |
| C5 identity convergence | AssetVersionReference is the only identity reference source |
| C6 schema hard removal | migration 20260902_0051 upgrades an empty PostgreSQL database and drops retired tables/columns |

## Required release evidence

- backend ruff and mypy;
- backend unit tests;
- PostgreSQL upgrade and alembic check;
- canonical Golden and RLS integration tests;
- frontend lint, typecheck, Vitest, build and Playwright;
- generated OpenAPI no-diff;
- security, repository policy and directory compliance;
- same-SHA runtime image health and source identity.

The first seven checks are orchestrated by docker-compose.quality.yml. A host
shell or an existing development container is not release evidence.

## Runtime contract

The only external application entry is port 8080. Port 8000 is the internal
API process port used by Compose networking and the frontend gateway. PostgreSQL,
Redis, MinIO and LiteLLM are internal services unless the development override
explicitly exposes them.

## Remaining scope

The Story chain is not part of this cleanup. After all C0–C7 gates are green,
create a separate Story Task Contract for Idea → Brief Proposal → Story
Direction Proposal → Script Draft → Structure Diff → ScriptDocument/Episode/
Scene/Shot. No Story Apply API is introduced by P10.
