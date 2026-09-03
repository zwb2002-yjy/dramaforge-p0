# V1 G7D — Dual-path real Golden + Final Film Artifact

**Task:** `v1-g7d-dual-path-final-film-20260903`
**Status:** COMPLETE（frozen `720bde4`；independent review branch 持有证据）

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

- real run JSON bound to frozen source SHA（success + negative probes）
- Final Film Artifact ffprobe duration 15–30s and MP4 signature
