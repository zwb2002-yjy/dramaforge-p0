# V1 Final Film evidence

This directory contains the sanitized dual-path evidence produced by
`scripts/prove_v1_current_head_golden.py`.

- Execution source: `94b5c2db37baaa57caa3ccdb5f5a86283a9ede67`
- Golden status: `ok=true`, `dirty=false`, 12 paid Agnes calls
- Final Film outputs: 15.146 seconds, 704×1280, H.264/AAC MP4
- Media assertions: burned Timeline subtitles, dialogue audio, source trim,
  Timeline subtitle overrides, and crossfade transitions

The Release Candidate workflow uploads this directory as
`v1-current-head-golden-<commit>`, so reviewers can download the JSON and both
playable MP4 files from the same candidate run.
