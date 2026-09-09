# V1 R6 — Frozen Timeline Final Film and independent subtitle delivery

**Task:** `v1-r6-final-film-subtitle-delivery-20260908`\
**Parent:** G7D / G7E / R6\
**Status:** IMPLEMENTED / VERIFIED (formal ledger registration unresolved)\
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

## Implementation evidence so far

- Added one millisecond Timeline map used for cut/crossfade offsets, trim/retime
  durations, subtitle cues, burn-in and summary evidence. Per-clip burn-in is
  replaced by a final subtitle pass using exactly the downloadable SRT bytes.
- Default dialogue is frozen separately from the user's idempotency request hash;
  same-key replay after a live dialogue edit retains the original queued result.
  Older queued snapshots may read their own frozen formal-reference dialogue,
  never a live Shot value. Explicit empty and disabled subtitles remain absent.
- SRT is an Artifact(type=subtitle) plus ExportItem(role=final_subtitle) with the
  same Export/NodeRun/Timeline version as MP4. Failed paired storage rolls back
  the entire delivery transaction and removes only its test/request-owned output
  objects; it cannot leave a half-published available Artifact.
- Subtitle-less/muted edits are valid exports; dialogue/burned-subtitle flags are
  diagnostic facts, not unconditional gates. Container, codecs, Timeline duration
  and requested subtitle behavior remain required and fail closed.
- Real FFmpeg tests generated local red/blue clips and music, verified H264/AAC,
  3.5-second overlapping Timeline, Unicode/multiline cues, trimmed/retimed source
  intervals, color-order samples, and an empty-subtitle export. They do not use
  app_env=test render substitutes and do not contact a real Provider.
- PG delivery tests verify hashes, ExportItem lineage, role-scoped access, same
  request replay, frozen dialogue and a second muted/empty Timeline version with
  zero new source-image/video ProviderOperations. UI exposes SRT download plus an
  explicit no-subtitle state in both current result and history.
- Focused renderer/worker/frontend tests pass. Full mounted-source precheck is
  underway; exact committed-candidate gates and evidence are still required.

- Full development precheck: backend unit 989 and integration 43 PASS; frontend
  unit 150, build and Playwright 19 PASS. Subsequent focused tests cover the last
  source-default idempotency refinement and storage atomicity. A 320x240 real
  fixture now starts with black leader frames: sampled red/blue output proves
  source-in trimming as well as ordering, and subtitle-band white pixel counts
  prove visible burn-in against the empty-caption render. No evidence screenshot
  was loaded or modified. Final same-commit validation follows this source commit.

## Exact-candidate result

Clean source `af4a0d8` passed backend unit 989, integration 43 (including real
FFmpeg and PostgreSQL paired delivery), frontend unit 150, Playwright 19, Ruff,
MyPy 243 files, migration drift, directory/canonical and generated API checks.
`tmp/r6-quality-contract/result-af4a0d8.json` binds image ids/source and structured
render, subtitle-lineage and zero-media-rerender facts. Complete logs and JUnit
are in the same directory. This closes R5's Timeline-only rerender delta proof.
No real paid Provider was used; R7/R8 and the root-ledger limitation remain.

For R7 preflight, the current 8080 stack was read-only inspected: its backend
services still advertise `worktree-acceptance-20260906-32216450fd43`, not this
candidate. No running services were replaced. Another task has created Wuzhen
contracts in the root; those inputs and any related runtime work were untouched.
