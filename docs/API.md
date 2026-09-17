# API — HTTP 表面权威

Status: current
Source: backend/app/api/v1 and generated OpenAPI
Date: 2026-09-16
Base: dev 6555395
Migration head: 20260916_0070
（入口见 [CURRENT.md](CURRENT.md)）

## Contract rules

- FastAPI OpenAPI is the only HTTP contract source.
- Frontend types are generated into frontend/src/shared/api/generated.ts.
- Frontend modules consume those schemas as `components["schemas"][...]`; they
  never re-declare a generated schema by hand. `npm run --prefix frontend
  api:authority` (CI `frontend-fast` and the container gate) fails when a
  frontend file re-declares a schema name that the generated contract owns.
- User-facing access is the frontend gateway at port 8080; the API process is
  an internal Compose service on port 8000.
- No compatibility endpoint is kept for retired product concepts.
- `backend/app/api/v1/router.py` registers 27 routers and exposes `/status`.

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
| Workbench | workbench.py | workspace state, Shot design, execution-plan preview, execution dispatch, formal selection, trace, staged repair (`repair-plan`, `repairs`, `repairs/{id}`, `repairs/{id}/steps`) |
| Director Assistant | director.py | proposal-only Shot suggestion and recommendation (`/director/shots/{shot_id}/...`), bounded Director turns, runtime start/control/resume signals, read-only runtime capabilities |
| Director board | director_board.py | per-shot 2D and rough-3D director board state — the only authoritative director-board writer |
| Review | review.py | evidence annotations and annotation decisions, plus the human review decision (`review-summary`, `review-decisions`) that admits an exact Artifact |
| Production monitor | production.py | Artifact bytes/frames, project snapshot, Outbox/Arq enqueue |
| Providers | provider_connections.py, provider_references.py, credentials.py, generations.py, model_profiles.py, model_candidates.py | model catalog, connection/credential revisions, capability probe and generation, reference delivery, model profiles (binding validation is an invariant of the save path, not a separate endpoint) and read-only candidates |
| Experiments | experiments.py | isolated Shot experiment branches; adoption is the ExperimentBranch decision, never a second adopt endpoint |
| Editing | editing.py, opencut.py, final_film.py | EditSession timeline, suggestion, export, OpenCut manifest, Final Film bound to a timeline version |
| Creative capabilities | creative_capabilities.py, workflow_planning.py | provider-neutral intent/capability planning and the read-only workflow-state aggregation; workflow/participation freeze is a domain action for Director/Workbench, not an HTTP surface |
| Events | events.py | SSE subscription with Last-Event-ID resume |
| Maintenance | maintenance.py | Owner-only recovery: list persisted failures, replay one Director wakeup or one Outbox dead letter with the expected failure identity |
| Worker tick | worker.py | worker-only HTTP tick for local/dev when Arq runs separately |

## Single authoritative write entry

Each product concept has exactly one write entry point. These writers were
retired as duplicate surfaces; the underlying domain logic stays where an
internal caller still needs it:

| Retired surface | Kept as the sole authority |
|---|---|
| `POST …/experiments/{experiment_id}/adopt` | the `ExperimentBranch` `decision` endpoint |
| `PATCH …/scenes/{scene_id}/shots/{shot_id}/director-board` | `DirectorBoardState` `GET`/`PUT` |
| `POST …/shots/{shot_id}/workflow-template`, `POST …/shots/{shot_id}/participation-plan` | the workflow/participation domain used by Director and Workbench |
| `POST /model-profiles/validate` | `validate_bindings`, enforced on the profile save path |

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

## Admission gates on the write surface

Three write paths refuse to continue until a stored fact says they may. Each is
validated server-side; a disabled button is never the only guard.

| Write path | Requirement | Refusal |
|---|---|---|
| `POST …/formal-keyframe`, `POST …/formal-video` | a stored human `approved` decision for that exact Artifact (`human_review_decisions`) | 422 `REVIEW_APPROVAL_REQUIRED` with `reason` (`REVIEW_AWAITING_HUMAN`, `REVIEW_DECISION_MISSING`, `REVIEW_DECISION_REJECTED`, `REVIEW_DECISION_STALE`) |
| `POST …/final-film/render` | the same decision for every clip Artifact on the frozen Timeline | 422 `DELIVERY_REVIEW_REQUIRED` with the offending `artifact_id` and `reason` |
| `POST …/repairs/{id}/steps` | the step being dispatched is a media step, not a human decision | 422 `REPAIR_STEP_REQUIRES_REVIEW` |

Review steps are human actions: the review page records the decision, and the
Formal selection stays a separate user action. A machine `needs_human` result is
evidence, never an approval.

## Cross-layer consistency contracts

- Asset status is `draft | active | recycled`; AssetVersion status is
  `candidate | formal | historical | rejected`. Ordinary Asset creation makes
  v1 Formal and stores it in `current_version_id`; `archived` is rejected.
- Asset create/update accepts top-level `tags`. `asset_tags` and
  `asset_tag_links` are the only tag query source; `metadata.tags` has no
  runtime meaning.
- `PATCH …/edit-sessions/{session_id}/timeline` requires
  `expected_session_version`, locks the row, and returns 409 without mutation
  when the loaded version is stale.
- `GET …/creative-capabilities/catalog` projects Genre, Style, Shot Language,
  Quality Policy, Skills, and staged strategies from the backend registries;
  the same registries validate Freeze requests.

## Idempotent submissions

Retries must not create a second operation:

| Endpoint | Key |
|---|---|
| `POST …/executions` | `Idempotency-Key`; the client derives it from the frozen plan fingerprint and reads `GET …/executions/receipt` before resubmitting |
| `POST …/assets/from-artifact` | `Idempotency-Key`; same key and input returns the original card, same key with different input is 409 `ASSET_CREATION_REQUEST_REUSED` |
| `POST …/review-decisions` | required `Idempotency-Key`; same key and input returns the original decision |
| `POST …/repairs`, `POST …/repairs/{id}/steps` | request key and per-step command key; a retry resumes the same step |
| `POST …/final-film/render` | `Idempotency-Key` plus a request fingerprint; reuse with a different body is rejected |

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
