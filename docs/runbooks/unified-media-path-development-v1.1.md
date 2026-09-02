# Unified media path development runbook

Status: current
Date: 2026-09-02

## Local development

Use Docker Compose for PostgreSQL, Redis, MinIO, LiteLLM, API, dispatcher and
Workers. The frontend gateway is the only host-facing application entry:
http://127.0.0.1:8080.

The API listens on port 8000 only inside the Compose network. Do not document
or use 8000 as an external application URL.

## Canonical execution

Shot execution is:

Workbench execution-plan preview → executions dispatch → Outbox → Arq Worker →
unified-v1 Provider compiler/runtime → ProviderOperation → Artifact.

Video requires the explicit formal keyframe. References are resolved from
ShotReferenceBinding and AssetVersionReference. No name-based fallback or
historical execution branch is available.

## Quality command

Run:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_in_docker.ps1

This builds the backend quality container with locked Python 3.12 dependencies
and the frontend quality container with locked Node 22 plus Chromium
dependencies. It runs static checks, unit tests, the full PostgreSQL integration
set, migration/contract checks, OpenAPI generation, frontend tests, build and
Playwright E2E. The command cleans only its explicitly named Compose quality
services afterward.

## Runtime smoke

For a no-cost smoke use the canonical proof script:

    python scripts/prove_formal_live_chain.py --scratch tmp/proof --idea "..." --script-file fixtures/scripts/episode_script.md

Paid Provider proofs require separate Owner authorization and must record the
exact source commit and redacted ProviderOperation evidence.

## Troubleshooting

- API health: http://127.0.0.1:8080/health
- gateway health: http://127.0.0.1:8080/gateway-health
- inspect internal services with docker compose ps/logs;
- if the quality image cannot build, repair Docker Hub/Debian/npm network access
  first; do not substitute host-installed dependencies and call the gate green.
