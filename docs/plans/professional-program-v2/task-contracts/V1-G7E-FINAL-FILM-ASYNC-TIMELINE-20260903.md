# V1 G7E — Timeline Final Film async render and evidence closure

**Task:** `v1-g7e-final-film-async-timeline-20260903`
**Status:** COMPLETE（最终验收由 R7 同候选收口）

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

All required gates now pass. Clean runtime candidate `adf1b94` passed focused
and full Docker quality gates, including real PostgreSQL/FFmpeg tests. Its R7
dual-path Golden and browser proof are committed under
`docs/reviews/evidence/v1-r7-current/`; both playable MP4s and matching SRTs are
available there and in GitHub artifact `10086615067`. Evidence/release commit
`3677430` changes no application, migration, frontend source or dependency
input after `adf1b94` and passed CI `34305028424`, Security `34305028341` and
Release `34305028423`.

The final evidence verifies frozen Timeline order/trim/duration/subtitle edits,
Worker-only Final Film execution, Export/Artifact idempotency, retry lineage,
dirty-draft UI protection, playable/downloadable delivery, and zero remote media
operations for editing-only rerender. The task is complete; only the Owner-only
G8 merge boundary remains.
