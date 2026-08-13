# MiniMax Provider Integration Contract

Task ID: `minimax-provider-integration`

Status: `COMPLETE`

Version: `1.0`

Baseline commit: `156e95a8b00ca50f7fbccfa04ae43e98fffcfe41`

## Outcome

Add MiniMax as a first-launch BYOK media Provider through the existing
`Catalog -> Plugin -> Compiler -> Runtime -> ProviderOperation` path. This task
adds a documented, contract-tested local implementation only. It does not
perform a real MiniMax request, account probe, media generation, or costed
operation.

## Frozen Scope

| Media | Provider/profile | Model/revision | Contracted request |
| --- | --- | --- | --- |
| Image keyframe | `minimax/minimax_cn_v1` | `image-01/v1` | One `character` `subject_reference` URL, fixed `aspect_ratio: 1:1`, synchronous URL response. |
| Shot video | `minimax/minimax_cn_v1` | `MiniMax-H3/v1` | One HTTPS `first_frame` image, fixed `resolution: 768P`, `duration: 5`, `ratio: adaptive`, asynchronous task. |

Official sources checked on 2026-08-13:

- https://platform.minimaxi.com/docs/api-reference/image-generation-i2i.md
- https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create.md
- https://platform.minimaxi.com/docs/api-reference/video-generation-v2-query.md
- https://platform.minimaxi.com/docs/api-reference/video-generation-v2-delete.md

## Fail-Closed Boundaries

- No image request is sent without exactly one `reference_image` URL.
- No video request is sent without exactly one `first_frame` HTTPS URL.
- The adapter rejects other image sizes and all video duration, resolution,
  aspect-ratio, audio, last-frame, and multi-reference requests.
- Create is single-attempt. A transport failure returns
  `unknown_submission`; the adapter never retries a potentially accepted POST.
- Polling uses only the persisted task ID. Resume tokens contain no secrets,
  raw request bodies, or short-lived media URLs.
- Provider API credentials remain BYOK environment or encrypted workspace
  credentials. They are never added to documentation, fixtures, tests, or
  commits.

## Owned Paths

- `backend/app/config.py`
- `backend/app/providers/minimax.py`
- `backend/app/providers/{registry,bootstrap,catalog_seed_data,workspace_credentials,connection_service}.py`
- `backend/alembic/versions/20260813_0021_minimax_catalog_entries.py`
- `backend/tests/unit/test_minimax.py`
- `backend/tests/unit/test_minimax_compiler.py`
- `backend/tests/unit/test_{provider_catalog,provider_registry,v3_registry,v3_generations}.py`
- `backend/tests/integration/test_{catalog_migration_pg,model_profiles_migration_pg}.py`
- `fixtures/providers/contracts/minimax-*.json`
- `.env.example`, `docker-compose.yml`
- `docs/开发执行检查点.md`

## Acceptance

1. Plugin registration, immutable catalog entries, V3 transports, model
   registry, runtime bridge, local and workspace BYOK configuration all resolve
   without Provider-specific branches outside `app/providers/`.
2. HTTP contract tests assert exact create/poll/cancel paths, authentication,
   payloads, response parsing, one-POST ambiguity behavior, and redaction.
3. Compiler tests prove an artifact reference enters each native request and
   unsupported request shapes fail before HTTP.
4. Alembic appends the MiniMax catalog entries without editing the frozen 0015
   historical seed migration.
5. Focused tests, static checks, and the relevant broader suite pass. A real
   Provider run remains blocked until the Owner grants a separate written scope,
   credentials method, retry policy, and per-run plus total cost ceilings.

## Completion Record

Completed on 2026-08-13. The local implementation, frozen catalog migration,
configuration wiring, fixtures, and mocked contract coverage are complete.
No real MiniMax request, account probe, media generation, or paid operation was
performed. The broader test suite encountered an intermittent Windows socket
resource error (`WinError 10055`); its affected test passed when rerun alone.
`mypy app` could not start because the local virtual environment failed to load
the `librt` base64 extension DLL, so no type diagnostics were produced.
