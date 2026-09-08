# V1 R6 — Frozen Timeline Final Film and independent subtitle delivery

**Task:** `v1-r6-final-film-subtitle-delivery-20260908`\
**Parent:** G7D / G7E / R6\
**Status:** IN PROGRESS\
**Baseline:** `dev@f4986f0`

## Authority and current evidence

The registered Owner 2026-09-07 revision (§10 R6) requires one frozen Timeline
mapping for rendering and final SRT: order, source in/out, adjusted duration,
transition overlap, muted/disabled/empty/multiline and edited subtitles. The
seven-plan Editing -> Production non-mutation and explicit export gates remain.

Existing Final Film already queues one project NodeRun, freezes a Timeline,
resolves formal video/tail audio and performs FFmpeg rendering. It does not
produce a final SRT Artifact/ExportItem. Empty subtitles fall back to live Shot
 dialogue at execution time, disabled subtitles fail an unconditional all-clips
subtitle assertion, and test-render duration ignores crossfade overlap. Per-clip
subtitle burn-in blends text during transitions instead of sharing a final SRT
cue map. These are verified gaps; do not rewrite the runtime/export engine.

## Outcome

- A single bounded, deterministic Timeline time map controls actual transition
  offsets, final duration, and final subtitle cue timing. Clamp/validate any cue
  to the rendered timeline, never concatenate fixed two-second Shot subtitles.
- Freeze missing/default subtitle text at queue time; preserve explicit empty,
  disabled and multiline values. Worker rendering does not read current Shot
  dialogue to replace a frozen user value.
- Render final burn-in and independent UTF-8 SRT from the same cue bytes/map.
  Store subtitle Artifact and ExportItem under the same Export/NodeRun/version
  as the MP4; keep source composite ids separate from delivery items.
- Add typed subtitle delivery metadata to Final Film result and a download link
  in current/history UI. Empty subtitles are explicit, not fake downloadable SRT.
- Real FFmpeg tests with generated local media prove order/trim/duration,
  crossfade/music/audio, subtitle text/disabled cases and successful ffprobe.
  Re-render after Timeline-only changes leaves image/video Provider calls and
  ProviderOperation counts unchanged. This is not the R7 paid Provider Golden.

## Owned paths

- `backend/app/production/timeline_subtitles.py` (new shared time/cue map)
- `backend/app/production/timeline_renderer.py`, `final_film.py`
- `backend/app/api/v1/final_film.py` only for typed result contract needs
- `frontend/src/features/editing/EditingWorkspace.tsx`, `api.ts`
- generated OpenAPI types
- focused final-film/subtitle unit, PostgreSQL/real-FFmpeg and frontend tests
- this contract and Goal status

## Non-scope / operational authorization

No new Export schema unless existing Artifact/ExportItem cannot express it. No
new Runtime, source production edits, automatic Formal choice, paid model calls,
production service replacement or Owner merge. Use existing project FFmpeg and
locked quality runtimes; generated synthetic local clips are test-owned only.
Preserve all existing files/evidence and independently-created Owner tasks.

## Acceptance

1. Cases with reordered clips, nonzero source in, changed duration and crossfade
   produce deterministic final timestamps matching actual MP4 duration.
2. Unicode/multiline text remains UTF-8; disabled/empty text stays absent; cues
   never become negative, zero-length or exceed final duration.
3. Same export/Timeline version exposes MP4 and SRT with verified hashes and
   produced_by_run_id/ExportItem linkage; history reads its frozen version.
4. Two exports after only subtitle/Timeline changes yield appropriate changed
   output, zero new image/video operations, and preserve Shot Formal truth.
5. Playable real H264/AAC render and ffprobe assertions pass without app_env=test
   substitute. UI has accessible subtitle download/empty-state and regression.
6. Full relevant backend/PG/generated frontend gates and exact-source evidence
   pass; failures remain reported and fixed in scope. R7/R8 still due afterward.
