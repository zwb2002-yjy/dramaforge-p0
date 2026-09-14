# PHASE_GATE

Status: P10 hard-removal gates complete; later Owner programs registered
Date: 2026-09-14
Base: dev 63935b9
Alembic head: 20260910_0066

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
| C7 contract/test/documentation closeout | generated OpenAPI, source scans, Docker quality gate, frontend format and Canonical inventories are aligned |

Later programs extended the same repository without reopening these gates:
Story authoring, the Workbench execution surface, Editing/Final Film delivery and
the independent Director runtime are registered as Owner amendments and bounded
Task Contracts under `docs/plans/professional-program-v2/`.

## Required release evidence

- backend directory-compliance and canonical-surface scans, ruff and mypy;
- backend unit tests;
- PostgreSQL upgrade and `alembic check`;
- canonical Golden and RLS integration tests;
- LiteLLM proxy integration test with the pinned image and mock models;
- frontend generated-API check, format, lint, typecheck, Vitest, build and Playwright;
- generated OpenAPI no-diff;
- same-SHA runtime image health and source identity.

These checks are orchestrated by docker-compose.quality.yml. A host shell, an
existing development container, or a re-used candidate image is not release
evidence.

## Runtime contract

The only external application entry is port 8080 (unprivileged Nginx gateway).
Port 8000 is the internal API process port used by Compose networking and the
frontend gateway. PostgreSQL, Redis, MinIO, LiteLLM and its metadata database are
internal services unless the development override explicitly exposes them.

Release topology services: postgres, redis, minio, litellm-db, litellm, migrate,
database-bootstrap, api, frontend, dispatcher, worker-default, worker-director,
worker-heavy. `maintenance` runs only under `--profile maintenance`.

## Scope boundaries that remain

- retired Quick / Creation / controlled-Director / CharacterReference surfaces
  must not return; the canonical-surface scan enforces this;
- Director Assistant stays proposal-only and never writes media;
- the Director runtime is an orchestration runtime: it never bypasses Apply,
  Save, Formal or Export gates, and MANUAL production must complete with the
  director worker stopped;
- Candidate → Formal, deletion and Export remain explicit user confirmations.
