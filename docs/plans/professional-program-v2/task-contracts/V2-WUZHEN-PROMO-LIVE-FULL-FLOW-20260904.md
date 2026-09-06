# Task: V2 — Wuzhen promo live dual-entry full flow

## Status

- **State:** COMPLETE
- **Task id:** `v2-wuzhen-promo-live-full-flow-20260904`
- **Goal:** Use the real local 5173 development entry and 8080 formal Nginx
  entry to create and finish one canonical Wuzhen promotional short-film
  Project. Diagnose, fix, test, rebuild, and rerun any blocking defect.
- **Baseline:** local `dev@2dae8abfe7f274e6b62da84faeb20e5a67e77b3f` (the final
  runtime source commit; the closeout document itself is docs-only);
  PostgreSQL migration `20260903_0055`; API, frontend, Dispatcher, default
  Worker, and heavy Worker all report this same source commit.

## Owner-supplied story material

六千年前马家浜文明在此生根，春秋吴越的烽烟、昭明太子的文脉，在潺潺车溪河畔沉淀。枕水而居的乌镇，古桥错落、水阁临波，桑蚕商贸繁盛，书香文脉绵延，诞生了茅盾、王会悟、木心等一众名人，民俗非遗生生不息，却也历经岁月动荡走向沉寂。1999年，乌镇开启古镇保护，坚守“修旧如故、以存其真”，不做静止的历史标本，在守护水乡风貌的同时植入现代生活，走出独树一帜的“乌镇模式”。古老江南不断拥抱新生，香市、蓝印花布延续烟火，乌镇戏剧节为古镇注入当代艺术活力；世界互联网大会永久落址于此，千年水乡连通数字世界。古韵与新潮在此相遇，乡愁与未来在此共生，乌镇，既是中国人心中梦里的枕水江南，更是向世界讲述中国古镇故事的鲜活窗口。

## Bounded production shape

- One new Project with a unique Wuzhen title; Free Start + ASSIST unless the
  live UI or Owner material establishes a better supported choice.
- Target: a coherent 15–30 second 9:16 promotional film, normally three
  approximately five-second visual beats: ancient water-town memory,
  preservation and living heritage, contemporary art/digital future.
- Story, ScriptDocument, Episode, Scene, Shot, Canvas, Candidate/Formal,
  EditSession/Timeline, Export, NodeRun, ProviderOperation, and Artifact remain
  the existing canonical facts. No test-only or second runtime path.
- 5173 performs the authoring path; 8080 cross-checks the same server facts and
  performs formal-entry review/edit/export acceptance. Both entries must remain
  usable throughout.
- Real paid Provider generation is permitted only after an action-time cost
  confirmation immediately before the first paid media submission. Reuse the
  configured encrypted credential; never print or copy it.

## Required flow

1. Create the Wuzhen Project and bind supported keyframe/video models.
2. Enter the supplied story material and produce/apply Canonical Story facts.
3. Produce at least three coherent Shots with narration/dialogue, duration,
   visual description, camera, image prompt, and video prompt.
4. Generate keyframe and video candidates through the real Outbox/Worker/
   Provider path; explicitly choose Formal results.
5. Verify review facts and create/load the EditSession Timeline.
6. Prepare voice/subtitle/composite tail and render Final Film asynchronously
   through the canonical Worker path.
7. Verify the final MP4 is playable/downloadable, 15–30 seconds, has video and
   audio/subtitles, and retains source/NodeRun/Artifact lineage.

## Verification and evidence

- Both entrypoints show the same Project/Scene/Shot/Formal/Editing facts.
- All containers remain healthy and source-commit aligned after any fix.
- No 500, unhandled exception, failed migration, stuck Outbox, or silent model
  fallback remains in the completed path.
- Record project/run/artifact identifiers, terminal statuses, media metadata,
  relevant hashes, and sanitized logs without credentials or signed grants.
- Any code fix receives a focused regression plus proportional backend,
  PostgreSQL, frontend, or browser verification before rebuilding the runtime.

## Live progress

- Created Project `c11be031-743c-45be-9d27-f8074e6d9e22` from the 5173 page as
  `乌镇·枕水新生宣传片 20260904-1614` (`FREE`, `ASSIST`, `9:16`).
- Reproduced a real application-role RLS defect on the first Story proposal:
  eight typed proposal items were persisted, but the POST response returned an
  empty operation list because `SET LOCAL app.*` was cleared by the route's
  internal commit. The fix rebinds owner/workspace/project scope before reading
  the response. A real PostgreSQL non-bypass regression now covers the commit
  boundary.
- Reproduced an ambiguous creative-capability target from the live Production
  page: it submitted both the selected Scene and Shot, the API froze the Scene,
  and the UI read the Shot. The client now submits the selected Shot only (or a
  Scene only when no Shot exists), while the API rejects zero or multiple
  targets. Unit, type, lint, format, and live dual-entry verification cover the
  target contract.
- The first paid keyframe click was rejected before NodeRun creation and before
  any ProviderOperation because the Workbench-prefixed client idempotency key
  exceeded the `VARCHAR(160)` persistence contract. Client keys are now scoped
  to stage + nonce (Project uniqueness is already the database scope), and the
  backend deterministically hashes any still-oversized caller key before
  persistence. The confirmed Provider-call allowance remains unused.
- Final Film preparation completed the first and third Formal tail, but the
  second composite failed closed because its 5.19s narration exceeded the
  5.04s Formal video by 0.15s. Composite rendering now preserves the complete
  narration with a bounded FFmpeg `atempo` speed-up (maximum 1.25x); larger
  mismatches still fail closed instead of truncating speech.
- After the successful retry and Final Film, Production Monitor still counted
  the superseded failed composite/continuity attempts as current risk and
  labeled Shot 2 `需处理`. The monitor and workbench now derive current status
  from the latest attempt per Shot + node + branch + experiment, while the full
  failed history remains available in the canonical snapshot and trace.

## Final verification record (2026-09-04)

- Canonical project: `c11be031-743c-45be-9d27-f8074e6d9e22`, title `乌镇·枕水新生宣传片 20260904-1614`, `9:16`, `FREE` + `ASSIST`; one ScriptDocument, one Episode, three Scenes and three Shots. Every Shot is `5.000s`, has dialogue plus image/video prompts, and has an explicitly selected Formal keyframe and Formal video.
- Provider path: three successful `agnes-image-2.1-flash` keyframe operations and three successful `agnes-video-v2.0` video operations, all through the canonical Outbox/Dispatcher/Worker path. No additional paid submission was made after the Owner's allowance of exactly three keyframes plus three videos.
- Formal artifacts: keyframes `a912b557-8179-4c9c-8600-3f2942c0d9f7`, `335eb089-b8fe-4a7c-98c3-50c4633ee1ae`, `e45836ba-2e4c-48f9-9b0d-28b8eac01985`; videos `4e11b4ec-df74-4cf2-8167-090f37a6b099`, `832e04ae-124a-4265-a870-71e688cd2cee`, `9f8f287e-df8a-4a40-9ed1-ea895feb14d5`. Review was opened on 8080 and showed all three Formal pairs.
- Editing: EditSession `5589c975-ba82-44b7-9780-538c1403fbc7`, timeline version `2`, three ordered clips and three burned subtitle lines. Export `4244f3c8-0bd5-4f98-9bc5-6bf5c2c53bd7` completed as `dramaforge-final-film-v1`.
- Final Film: run `09bbd5eb-9f92-4c08-9bbf-00fa19fe424e`, artifact `4a9599e7-75a4-42fd-97f5-f1100e875fc5`, `video/mp4`, `704×1280`, `15.173s`, `8,604,429` bytes, SHA-256 `5f3acb71912f980d4e983164b4ed7064133ead80cffbdd3033037189595c5753`. ffprobe records H.264 video and AAC audio; export assertions for MP4, H.264, AAC, burned subtitles, dialogue audio, and applied timeline edits are all true. The playable local copy is `tmp/wuzhen-final-film/wuzhen-pillow-water-rebirth-c11be031.mp4`.
- Tail repair: the first Shot 2 composite failed closed on a `5.19s > 5.04s` narration/video mismatch. The bounded `atempo` fix allowed the successful attempt-2 composite `819e08c7-0416-44ce-94f3-89664631fbdd` and continuity `31d1d88d-3c7a-4ee9-82e2-faf1de2ebd05`; no speech was truncated. Historical failed attempts remain auditable, while the current monitor reports zero risk.
- Runtime: migration `20260903_0055`; all five app containers are healthy and image label plus backend environment source identity is `2dae8abfe7f274e6b62da84faeb20e5a67e77b3f`. Current Outbox status is fully `published`, dead-letter count is `0`, and there are no queued/running runs for this project. The two historical failed runs are superseded by successful attempt-2 lineage.
- Browser acceptance: 5173 authoring and 8080 formal/review/edit entrypoints showed the same project, three-scene/three-shot, Formal, Editing, and Final Film facts. On 8080 the HTML video loaded without media error and advanced during playback; 5173 returned the same artifact id, hash, duration, download target, and completed export through idempotent export lookup.
- Sanitized machine-readable evidence is kept in `tmp/wuzhen-final-film/evidence.md` alongside the playable MP4.

## Allowed implementation scope

- The smallest backend/frontend/test/migration paths required by a reproduced
  blocker in this exact flow.
- This Task Contract and sanitized evidence under `tmp/` or the established
  review evidence path.
- No unrelated UI phase, roadmap expansion, legacy restoration, biometric
  scoring, automatic fallback, or alternate generation truth.
