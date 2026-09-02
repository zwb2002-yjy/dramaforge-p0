# P10-C6/C7 — Schema, API, tests, and documentation closeout

**Status:** USER-AUTHORIZED / IN PROGRESS
**Parent:** P10 legacy hard removal
**Alembic revision:** 20260902_0051

## Outcome

The database, OpenAPI, source inventories, tests, and development gates all
describe the same reduced Canonical product. The hard-removal migration is
irreversible by explicit Owner decision and never deletes canonical projects,
Shots, Artifacts, ProviderOperations, or EditSessions.

## Gate ownership

- C6: migration 0051, model registry, RLS policy replacement, and PostgreSQL
  empty/current-schema upgrade;
- C7: generated API types, source scans, backend/frontend checks, and
  docker-compose.quality.yml;
- release: exact-source image build and runtime health/source identity.

## Deferred

The new Story authoring chain and its Apply API are a separate task after this
contract is complete. No Story UI or second story truth is added here.
