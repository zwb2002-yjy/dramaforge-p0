# DramaForge V1 reconciliation — 2026-09-07

**Candidate source:** `dev@15a0b41338d51eeb2da162180869f45291fd5aef`\
**Result:** R0 PASS; the complete V1 Goal remains BLOCKED by R1–R8.\
**Evidence rule:** code existence, automated checks, live runtime behavior and
release readiness are recorded separately.

## Source and environment identity

| Surface | Authoritative observation | Result |
|---|---|---|
| local / remote source | fetched `origin/dev` and fast-forwarded local `dev` to `15a0b413`; no tracked user edits were present | PASS |
| pre-existing user work | two root Markdown files remain untracked and untouched | PRESERVED |
| CI | run `34054711617`, head `15a0b413`, success | PASS FOR SOURCE |
| Security | run `34054711552`, head `15a0b413`, success | PASS FOR SOURCE |
| Release | run `34054711575`, head `15a0b413`, skipped | NOT PASSED |
| running backend | one digest for API/dispatcher/default/heavy Worker; revision `worktree-acceptance-20260906-32216450fd43` | HEALTHY, NOT CURRENT HEAD |
| running frontend | digest `sha256:eb25c…47376`; same worktree revision label | HEALTHY, NOT CURRENT HEAD |
| migration | application head and live PostgreSQL both `20260903_0055` | PASS FOR CURRENT RUNTIME |

## Existing-project read-only recovery

The 8080 Project Lobby loaded successfully. Opening existing project
`Free ASSIST Golden 51c350a7` recovered its Rooftop Scene with three Formal
keyframes and three Formal videos. Editing listed and reopened EditSession
`8048152e-ff2f-4cd0-9787-d4d593e73cc1` at timeline v2, then exposed completed
Final Film Artifact `258be0d5-d195-4413-933a-085f84bd76c8` as `video/mp4`,
3,262,343 bytes, with content hash
`766527a32607ecf5fc5a291fcde7216997deafc234ecf3e4b37b859cb3a1d0ce`.
The UI provides MP4 playback/download and no final SRT download. The check did
not create a project, EditSession, export or Provider request.

## G7E item-by-item reconciliation

| Requirement | Code | Automated/current evidence | Live observation | State / owner |
|---|---|---|---|---|
| frozen Timeline drives clip order, trim, duration, subtitle, audio, music and transitions | implemented in `production/final_film.py` and `timeline_renderer.py` | historical focused tests and Golden exist; not rerun for a new candidate | existing v2 MP4 reports timeline edits/subtitles/audio applied | IMPLEMENTED, final true-render evidence remains R6/R7 |
| HTTP enqueues; Outbox/Worker renders and persists terminal state | implemented | historical runtime and tests exist | separate API/dispatcher/Workers healthy | IMPLEMENTED, failure/recovery matrix remains R5 |
| retry attempt and idempotency semantics | implemented | unit/PG evidence exists but is not a future-candidate gate | no mutation performed | REVERIFY R5 |
| Editing waits, blocks dirty export and recovers playable artifact | mostly implemented | existing component/E2E evidence | EditSession v2 and completed MP4 recovered without regeneration | IMPLEMENTED; Scene wait/draft gaps are R1 |
| same-head Golden, MP4 and CI/Security/Release | historical evidence only | current CI/Security pass; Release skipped | live image is not `15a0b413` | BLOCKED BY R7/R8 |

## Revision requirement matrix

| Revision requirement | Current evidence | Decision | Owning task |
|---|---|---|---|
| Scene active-run automatic refresh | `SceneWorkspace` query has no `refetchInterval` | confirmed defect | R1 |
| dirty draft survives panel close and guarded Shot/page change | panel close is safe, but selected-Shot effect clears `designDirty` and suggestion draft unconditionally | confirmed defect | R1 |
| real text Director through product entry | Shot/Editing/Recommendation defaults are deterministic; Story requires caller draft | missing capability | R2 |
| correct shot-scoped context | `AssistantContextBuilder` loads `Scene` with the Shot ID before loading the Shot | confirmed defect | R2a |
| effective user intent / Skill / style / model request identity | compiler/runtime structures exist; end-to-end semantic trace not current-candidate proven | not verified | R3 |
| persistent bounded AUTO/ASSIST/MANUAL turn coordination | no `DirectorTurn` implementation found | missing capability | R4 |
| typed recovery/retry matrix | mechanisms exist; future-candidate fault evidence incomplete | reverify, fix only reproduced gaps | R5 |
| final Timeline SRT | renderer creates temporary per-clip burn-in SRT; Export exposes only MP4 | missing deliverable | R6 |
| two real creation paths and MANUAL regression | historical Golden exists, new Director/SRT behavior not covered | blocked by R1–R6 | R7 |
| same SHA/images/migration/evidence Release candidate | `15a0b413` Release skipped and live images have a worktree identity | not satisfied | R8 |

## Next executable task

R1 is dependency-ready and has four observable acceptance targets: active-run
polling to terminal state, per-Shot draft retention, guarded navigation with
save/discard semantics, and accurate submitted-versus-running stage actions.
Its bounded contract is `V1-R1-SCENE-WORKFLOW-20260907.md`.
