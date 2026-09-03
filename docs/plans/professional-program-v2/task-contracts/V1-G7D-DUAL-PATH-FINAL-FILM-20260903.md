# V1 G7D — Dual-path real Golden + Final Film Artifact

**Task:** `v1-g7d-dual-path-final-film-20260903`
**Status:** COMPLETE

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

- real run JSON：`backend/tmp/golden-current-06dd369.json`，SHA-256
  `bffafbae6976b34dc9fff02d2ec00cdc40e4002ab60923d750ae73e7e9ed01e2`；
  `source_commit=06dd369`、`dirty=false`、`ok=true`；
- Template+AUTO 与 Free+ASSIST 各 3 shots，真实 Agnes keyframe/video 共 12 次；
- 两条 Final Film 均为 15.233s、`video/mp4`、H.264/AAC、dialogue audio、
  burned subtitles；两条并发 render 均证明相同 Export/Artifact；
- negative probes fail closed（409/422、无新增 NodeRun）；resilience 49 tests
  passed；执行 identity 的 connection/credential revision 全部冻结。
