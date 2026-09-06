# V1 G7D — Dual-path real Golden + Final Film Artifact

**Task:** `v1-g7d-dual-path-final-film-20260903`
**Status:** IN PROGRESS（验收复核重新打开；由 G7E 收口）

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

The final gate remains blocked until CI, Security, and Release Candidate all
report this evidence on the final pushed HEAD.
