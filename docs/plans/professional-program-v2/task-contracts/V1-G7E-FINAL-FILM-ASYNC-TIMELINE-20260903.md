# V1 G7E — Timeline Final Film async render and evidence closure

**Task:** `v1-g7e-final-film-async-timeline-20260903`
**Status:** IN PROGRESS

## Review-driven scope

1. Final Film must render the persisted EditSession Timeline, including clip
   order, source in/out, timeline duration, subtitle text, selected audio,
   optional music, and supported transitions; it must not merely concatenate
   whole-shot composites.
2. The HTTP path may validate and enqueue only. Final Film rendering, object
   storage, Export/ExportItem persistence, and terminal failure handling run in
   the canonical Outbox → Worker path.
3. Final Film NodeRuns use a computed attempt number. A failed attempt can be
   retried with the same external idempotency key, while a completed Export
   remains idempotent and rejects key reuse for a different Timeline request.
4. The Editing UI must wait for the prepared tail and queued Final Film job,
   block export while the Timeline draft is dirty, and expose a playable and
   downloadable Artifact when complete.
5. The final Golden JSON and at least one playable Final Film evidence artifact
   must be uploaded and bound to the same final PR HEAD as CI/Security/Release.

## Owned paths

- `backend/app/production/final_film.py`
- `backend/app/api/v1/final_film.py`
- `backend/app/execution/product_path.py`
- `backend/app/runtime/scheduler.py`
- `backend/app/workers/jobs.py`
- `frontend/src/features/editing/EditingWorkspace.tsx`
- `frontend/src/features/editing/api.ts`
- focused Final Film, scheduler, worker, and Editing UI tests
- `scripts/prove_v1_current_head_golden.py`

## Gate

The task remains blocked until focused tests, full Docker quality gates, a
real dual-path Golden, accessible Golden/MP4 evidence, and same-HEAD GitHub
CI/Security/Release checks all pass.
