# Model support matrix

Generated from `backend/app/providers/model_catalog/` and optional redacted Binding status.
Provider capabilities are recorded independently of the Workbench product subset.
A documented preview cannot execute. A verified Binding is workspace-specific.

| Provider | Model / revision | Lifecycle | Media | References | Duration | Resolution / size | Account | Executable | Certified |
|---|---|---|---|---|---|---|---|---|---|
| agnes | `agnes-image-2.1-flash` / `v2` | active | image | reference_image ≤ 1 | — | 1K | workspace-specific | requires verified Binding | workspace-specific |
| agnes | `agnes-image-2.5-flash` / `2026-09-28-candidate` | preview | image | reference_image (limit unverified) | — | 1K, 2K, 3K, 4K | workspace-specific | no | workspace-specific |
| agnes | `agnes-video-2.5` / `2026-09-28-candidate` | preview | video | first_frame ≤ 1, last_frame ≤ 1, reference_audio ≤ 3, reference_image ≤ 8, reference_video ≤ 1 | 4–12 | 720P, 1080P, 1K, 2K | workspace-specific | no | workspace-specific |
| agnes | `agnes-video-2.5-flash` / `2026-09-28-candidate` | preview | video | first_frame ≤ 1, last_frame ≤ 1, reference_audio ≤ 3, reference_image ≤ 5 | 4–12 | 720P | workspace-specific | no | workspace-specific |
| agnes | `agnes-video-v2.0` / `v1` | active | video | first_frame ≤ 1 | — | 9:16 | workspace-specific | requires verified Binding | workspace-specific |
| minimax | `MiniMax-H3` / `v1` | active | video | first_frame ≤ 1 | 5 | 768P | workspace-specific | requires verified Binding | workspace-specific |
| minimax | `MiniMax-H3` / `v2` | preview | video | first_frame ≤ 1, last_frame ≤ 1, reference_audio ≤ 3, reference_image ≤ 9, reference_video ≤ 3 | 4–15 | 768P, 2K | workspace-specific | no | workspace-specific |
| minimax | `MiniMax-H3-Max` / `2026-09-28-candidate` | preview | video | first_frame ≤ 1, last_frame ≤ 1, reference_audio ≤ 3, reference_image ≤ 9, reference_video ≤ 3 | 5–15 | 480P, 768P | workspace-specific | no | workspace-specific |
| minimax | `image-01` / `v1` | active | image | reference_image ≤ 1 | — | 1024x1024 | workspace-specific | requires verified Binding | workspace-specific |
| minimax | `image-01` / `v2` | preview | image | reference_image ≤ 1 | — | 1:1, 16:9, 4:3, 3:2, 2:3, 3:4, 9:16, 21:9 | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedance-1-0-pro-250528` / `v1` | active | video | first_frame ≤ 1 | — | — | workspace-specific | requires verified Binding | workspace-specific |
| volcengine | `doubao-seedance-2-0-260128` / `v1` | active | video | first_frame ≤ 1 | — | — | workspace-specific | requires verified Binding | workspace-specific |
| volcengine | `doubao-seedance-2-0-260128` / `v2` | preview | video | first_frame (limit unverified), last_frame (limit unverified), reference_audio (limit unverified), reference_image (limit unverified), reference_video (limit unverified) | 4–15 | 480p, 720p, 1080p, 4k | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedance-2-0-fast-260128` / `2026-09-28-candidate` | preview | video | first_frame (limit unverified), last_frame (limit unverified), reference_audio (limit unverified), reference_image (limit unverified), reference_video (limit unverified) | 4–15 | 480p, 720p | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedance-2-0-mini-260615` / `2026-09-28-candidate` | preview | video | none documented | — | — | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedance-2-5-260628` / `2026-09-28-candidate` | preview | video | first_frame ≤ 1, last_frame ≤ 1, reference_audio ≤ 10, reference_image ≤ 30, reference_video ≤ 10 | 4–30 | 480p, 720p, 1080p | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedream-4-0-250828` / `v1` | active | image | reference_image ≤ 1 | — | 2048x2048 | workspace-specific | requires verified Binding | workspace-specific |
| volcengine | `doubao-seedream-4-0-250828` / `v2` | preview | image | reference_image ≤ 14 | — | — | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedream-4-5-251128` / `2026-09-28-candidate` | preview | image | reference_image ≤ 14 | — | — | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedream-5-0-260128` / `2026-09-28-candidate` | preview | image | reference_image ≤ 14 | — | — | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedream-5-0-flash-260915` / `2026-09-28-candidate` | preview | image | reference_image ≤ 10 | — | 1K, 1.5K, 2K | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedream-5-0-lite-260128` / `2026-09-28-candidate` | preview | image | reference_image ≤ 14 | — | — | workspace-specific | no | workspace-specific |
| volcengine | `doubao-seedream-5-0-pro-260628` / `2026-09-28-candidate` | preview | image | reference_image ≤ 10 | — | 1K, 1.5K, 2K | workspace-specific | no | workspace-specific |

No account verification or certification is inferred from a catalog manifest.
