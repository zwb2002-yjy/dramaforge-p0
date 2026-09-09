# V1 G7D — Dual-path real Golden + Final Film Artifact

**Task:** `v1-g7d-dual-path-final-film-20260903`
**Status:** COMPLETE（最终验收由 R7 同候选收口）

## Required by Owner review

1. Template+AUTO and Free+ASSIST must both complete an equal real full main
   chain (keyframe/video Formal + voice/subtitle/composite + Final Film).
2. Final Film must be a playable 15–30 second MP4 Artifact with dialogue voice
   and burned subtitles, retaining voice/subtitle/composite and Formal Shot
   lineage through `Export`/`ExportItem`.
3. Golden must also prove fail-closed negative probes, execution identity
   freeze, and idempotency evidence.

## Implementation owned paths

- `backend/app/production/final_film.py`
- `backend/app/api/v1/final_film.py`
- `backend/app/execution/experiment_nodes.py`
- `backend/Dockerfile` / `backend/Dockerfile.quality`（CJK fonts for subtitles）
- `scripts/prove_v1_current_head_golden.py`

## Evidence after freeze

The prior `06dd369` evidence is superseded by the review-follow-up run. The
new clean runtime execution commit is
`94b5c2db37baaa57caa3ccdb5f5a86283a9ede67`; its evidence is kept under
`docs/reviews/evidence/v1-current-head/` and uploaded by the Release Candidate
workflow for `[release-candidate]` pushes.

- Golden JSON: `golden-current-94b5c2d.json`, SHA-256
  `6b17c344f4967da3de63b04c0137cef4fc4660ca42e3a10694d794c2aedad23c`；
  `source_commit=94b5c2d…`、`dirty=false`、`ok=true`；
- Template+AUTO and Free+ASSIST each completed 3 shots and the same full
  Formal → Tail → Final Film chain, with 12 paid Agnes calls total；
- both Final Films are 15.146s `video/mp4` H.264/AAC with dialogue audio,
  burned Timeline subtitles, trim, subtitle override, and crossfade evidence；
- concurrent Final Film requests share one queued Worker NodeRun, Export, and
  Artifact; failed retries use the next `attempt_no` and same external key.

## Final acceptance closure — 2026-09-09

The old `94b5c2d` review-follow-up is superseded by the final R7 evidence under
`docs/reviews/evidence/v1-r7-current/`. Runtime candidate `adf1b94` and
evidence/release candidate `3677430` prove the required dual-path result:

- Template+AUTO has five Formal shots and a 24.027-second 704×1280 H.264/AAC
  Final Film with dialogue, burned Timeline subtitles and an independent SRT;
- Free+ASSIST has four Formal shots and a 19.239-second 704×1280 H.264/AAC
  Final Film with dialogue, burned Timeline subtitles and an independent SRT;
- both paths preserve Formal Shot, voice/subtitle/composite, NodeRun, Artifact,
  Export and frozen EditSession lineage in the same canonical runtime;
- negative boundaries, frozen execution identity, local/remote recovery,
  request idempotency and editing-only zero-media rerender all pass;
- CI `34305028424`, Security `34305028341` and Release `34305028423` pass on
  `3677430`, and both films are present in uploaded artifact `10086615067`.

All three Owner-review requirements are satisfied. Owner merge remains the G8
boundary and is not part of this completed implementation contract.
