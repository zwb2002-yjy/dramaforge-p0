# Composite Media Contract

Task ID: `composite-media-contract`

## Outcome

The `composite` node is a local media operation. It consumes the latest
successful video, voice, and subtitle Artifacts for its exact
`graph_version_id` and `shot_id`, then produces one `video/mp4` Artifact with
the voice muxed and the SRT subtitles burned in. It never invokes Agnes, Kling,
or creates a ProviderOperation.

## Scope

- Add a composite-only execution branch before Provider adapter selection.
- Resolve, validate, and snapshot the three input Artifact lineages.
- Use deterministic test bytes only when `APP_ENV=test`.
- Use local FFmpeg and fail closed outside test.
- Add unit coverage for local-only execution, lineage, missing inputs, and
  formal FFmpeg failure behavior.

## Out Of Scope

- Changing remote video, voice, subtitle, or Provider adapter behavior.
- Adding a new database schema or changing Graph topology.
- Export-level FFmpeg behavior.

## Preconditions

- Task branch: `agent/composite-media-contract`.
- Task worktree: `.worktrees/composite-media-contract`.
- ObjectStore is available to the Worker.
- Formal environments provide a usable `ffmpeg` executable.

## Acceptance Evidence

- A successful composite has no ProviderOperation and invokes no supplied
  Provider adapter.
- `input_snapshot.media_inputs` and `output_summary.media_inputs` contain the
  Artifact id, object key, content hash, MIME type, and source NodeRun id for
  video, voice, and subtitle.
- A missing, unavailable, or unreadable input fails as
  `COMPOSITE_INPUT_MISSING` without a ProviderOperation.
- Test mode returns deterministic composite bytes; development and production
  use FFmpeg and persist a terminal failure when it fails.
- Focused tests, Ruff, mypy, backend unit regression, and review pass.

## Owned Paths

- `backend/app/execution/product_path.py`
- `backend/app/execution/composite_media.py`
- `backend/tests/unit/test_composite_media.py`
- `docs/task-contracts/composite-media-contract.md`

## Completion Definition

The scoped implementation and tests are committed on the Task branch with all
acceptance evidence recorded in the Task completion ledger event.
