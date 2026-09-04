# Task: V2 — Wuzhen promo live dual-entry full flow

## Status

- **State:** IN PROGRESS
- **Task id:** `v2-wuzhen-promo-live-full-flow-20260904`
- **Goal:** Use the real local 5173 development entry and 8080 formal Nginx
  entry to create and finish one canonical Wuzhen promotional short-film
  Project. Diagnose, fix, test, rebuild, and rerun any blocking defect.
- **Baseline:** local `dev@218792909ea054e622c9c52b1609fa47969b771b`;
  PostgreSQL migration `20260903_0055`; API, frontend, Dispatcher, default
  Worker, and heavy Worker all report the baseline source commit.

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

## Allowed implementation scope

- The smallest backend/frontend/test/migration paths required by a reproduced
  blocker in this exact flow.
- This Task Contract and sanitized evidence under `tmp/` or the established
  review evidence path.
- No unrelated UI phase, roadmap expansion, legacy restoration, biometric
  scoring, automatic fallback, or alternate generation truth.
