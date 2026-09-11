# V1-D8-CANDIDATE-ACCEPTANCE-20260910

Status: BASE CANDIDATE MERGED; TERMINAL-RUNTIME CORRECTION VERIFIED LOCALLY.
PR #79 merged the D0-D8 base into `main` as `986cd5e`. The playable deliveries
remain valid, but a post-merge database audit found that candidate `3c728a3` did
not advance eight media-bound Director Turns past their production checkpoint.
Correction commit `4e61d6f` fixes that boundary and has passed the complete local
Gate; it still requires review and integration before the final source is done.

Owner authorization for the paid run: “测到满意” (run until satisfied), applied
under the Owner implementation §12.1 rule to reuse existing configured facts and
produce only the minimum necessary new calls.

Authority: Owner implementation §12, Owner design §§8–11, the D0–D7 contracts,
and the Professional R6/R7 delivery contracts. Old candidate evidence remains
historical and is not relabelled as proof for this runtime revision.

Outcome: bind a new source candidate to Template+AUTO, Free+ASSIST and
Director-off MANUAL paths; prove shared production facts, explicit decisions,
Formal/Review/Repair/Editing/Export gates and playable MP4/SRT delivery; package
reviewable source/image/runtime/evidence identities without claiming release
before those identities match.

Current local candidate evidence (2026-09-10):

- Working base SHA: `4de7acd14481e262346fb0a4802d7725586194ed`.
  The working tree contains the uncommitted D0–D8 implementation, so this SHA
  is a base identity rather than a releasable candidate identity.
- MANUAL director-off verification starts from an empty Free project whose
  canonical `director_autonomy` is `MANUAL`. It imports one explicit Story,
  records offline fixture keyframe/video production facts, makes explicit
  Formal selections, creates Review/Repair facts, saves an EditSession timeline
  and calls the existing Final Film queue/worker path.
- During that chain `DirectorTurn`, `DirectorRuntimeControl` and
  `DirectorRuntimeWakeup` counts stay zero. Network Provider calls are zero.
  The fixture source media are clearly labelled `offline_fixture`; the final
  render is the real local FFmpeg production implementation.
- The resulting first delivery is a 2.508-second H.264/AAC MP4 plus independent
  UTF-8 SRT. A second subtitle/Timeline version creates another Final Film while
  the source image/video ProviderOperation id set remains unchanged.
- Machine-readable evidence and local deliverables are in
  `tmp/v1-d8-local/evidence.json`, `manual-director-off.mp4` and
  `manual-director-off.srt`. Recorded SHA-256 values are
  `ac2b8476123cb9355c2c37292bd50dc05a40fc586b94db11adad43571eaf185e`
  and `9964100c81f892e73e2a4b434daf4ad5edfb16f7e1cfd3fef82dc984cc185cce`.
- The real FFmpeg clock/crossfade/subtitle test and PostgreSQL paired MP4/SRT
  lineage test both pass. Full backend/frontend regression evidence is recorded
  in D6/D7.
- ~~The quality images built from the verified runtime source are locally
  identified as backend
  `sha256:4c13532a4a2b068cfce912b6e28756ed618b1a8e85a7fe6e2004ee5bfd2be55d`
  and frontend
  `sha256:6bf7577adad5930ea7cd209a9b399dee628dc0503b6a86d9726af7d8816e1ec8`.~~
  **This image identity was withdrawn as stale; see "Identity correction"
  below.** Neither digest exists in the local image store, and the byte set it
  claimed to identify had already changed.
- Identity correction (2026-09-10, later run). The manifest recorded at
  18:45:29 and the claim above were stale: `frontend/src/features/shots/api.ts`,
  `frontend/src/features/shots/ShotProductionActions.tsx` and
  `frontend/tests/unit/ShotProductionActions.test.tsx` were modified at
  18:46:47, after that manifest was generated. The finding and the accidental
  local `pnpm` mutation encountered while investigating it are recorded in
  `tmp/v1-d8-identity-20260910/drift-and-repair.json`; the environment was
  restored with `npm ci` against the unchanged `frontend/package-lock.json`
  (`afae842e…`) and no tracked file was changed by that repair.
- The full quality Gate was re-run from the current worktree and passed:
  directory/canonical checks, Ruff, mypy (277 files), 1,041 backend unit tests,
  Alembic upgrade through `20260910_0066` plus `alembic check`, 74 integration
  tests (`--fail-on-skip`, 221.34 s), generated-API equivalence,
  Prettier/ESLint/TypeScript, 155 frontend unit tests, the production build,
  20 Playwright tests and 5 isolated LiteLLM proxy tests. Provider calls were
  zero. The failed first attempt (a PowerShell `NativeCommandError` caused by
  merging compose's stderr into the pipeline, not a repository defect) is kept
  in the same evidence directory.
- The re-derived identity binds the current 796-file byte set: the host
  manifest, the backend quality image manifest and the frontend quality image
  manifest are byte-identical at
  `3c7a744472f205cefc9177ecf5c86100319c31443005b09169302136ad8f3f3b`, with
  0 missing files and 0 hash differences against both images. The images built
  from this byte set are backend
  `sha256:e4729a145d47bfc8146561a57dcbbe8ec95b9e2e52e72f8cfb2da554b2073818`
  and frontend
  `sha256:ab2e376c810102fbb4f43090ea8ddb76298ffc21eda67da93ab0fd0b9fa40128`.
  Full detail: `tmp/v1-d8-identity-20260910/identity.json`. These identify the
  verified dirty-worktree runtime build; they are still not promoted as release
  images until a source commit is frozen and rebuilt from that commit.

Acceptance state:

| Path | State | Evidence/remaining gate |
|---|---|---|
| MANUAL, Director stopped | REAL PASS | Empty project through playable MP4/SRT, zero Director rows and zero source regeneration on rerender |
| Free + ASSIST | DELIVERY PASS; RUNTIME CORRECTION PENDING INTEGRATION | Real Story/Shot/Editing decisions and a 19.239 s MP4/SRT remain valid. The retained DB exposed incomplete terminal-fact continuation on `3c728a3`; `4e61d6f` fixes and tests it without media resubmission |
| Template + AUTO | DELIVERY PASS; RUNTIME CORRECTION PENDING INTEGRATION | Exactly one NodeRun was created per authorization and the 19.239 s MP4/SRT remains valid. The bound Turn continuation is corrected by `4e61d6f` |
| Source/image/runtime identity | CANDIDATE FROZEN AND REBUILT | Commit `3c728a3` frozen; runtime images rebuilt from that commit and verified to report it; the earlier claimed digests stay withdrawn |
| Release/Owner merge | BASE MERGED; FOLLOW-UP REQUIRED | PR #79 was merged by the Owner account at 2026-09-11 07:54:04Z (`986cd5e`). The terminal-runtime correction is a later bounded commit and needs its own review/integration |

Completion-criterion audit against Owner design §12:

| Criterion | Current evidence | Local result |
|---|---|---|
| Production independent of Director | Empty MANUAL project reaches the canonical Final Film worker with zero Turn/control/wakeup rows | PASS |
| One production kernel | Manual and delegated commands both enter `ProductionCommands` and the same NodeRun/Outbox/Arq/ProviderOperation/Artifact chain; the real run produced 8 remote media operations per path | PASS |
| Recoverable Director | `3c728a3` rejected the terminal fact projection and allowed Formal to reach the wrong checkpoint; `4e61d6f` adds typed projection, stage gating and canonical-fact reconciliation | CORRECTED LOCALLY; FOLLOW-UP INTEGRATION REQUIRED |
| Replayable side effects | Stable authorization/receipt plus invocation unknown-submission rules prevent a second model/media create; the editing-only rerender added 0 remote media operations | PASS |
| Fresh context Gate | Shot/profile versions, revoke races, MANUAL changes, fencing and RLS reject stale/cross-scope actions | PASS |
| One domain truth | SDK state stores flow position/receipts only; Proposal, Formal, NodeRun, Artifact and Export remain canonical records; the canonical Proposal decision alone advanced the bound turn | PASS |
| Replaceable engine boundary | Application contracts contain no LangGraph/private SDK types; engine routing is immutable per Turn | PASS |
| Product behavior | AUTO delegation, ASSIST decisions, independent manual controls, Review/Repair/Editing and MP4/SRT paths pass controlled regression plus the real candidate run | PASS |
| Trustworthy current candidate | The exact candidate delivered both films, but its retained DB disproved full runtime convergence. The correction source has a new full Gate and preserves the real artifacts | BASE CLAIM CORRECTED |

Candidate-bound real acceptance (2026-09-10, later run):

- Runtime identity: commit
  `3c728a356c4c49bb52110b7cceaaa9ca87c6884e`, reported by `/health`
  `source_commit` and embedded as the `org.opencontainers.image.revision`
  label. Backend image
  `sha256:d9a6b840047b40d1db5cfd05758bcbfdcb91cc260f5c6201f605164260c540d6`,
  frontend image
  `sha256:5683252478063820c23cf04f439d9e6e1fa0ca5a0d18efc977321388a5111141`.
- The run used an isolated Compose project with its own volumes. Provider and
  model configuration was copied from the retained acceptance copy of the
  authorized workspace after verifying the target was empty; the production
  database was neither started nor migrated, and no production data was
  modified. MiniMax and Volcengine remain unconfigured and are recorded as
  NOT VERIFIED rather than substituted.
- Harness `scripts/prove_v1_d8_acceptance.py`, state and evidence in
  `tmp/v1-d8-acceptance-20260910/`. Every paid step is persisted before its
  request and is never replayed.
- Media generation was bounded to the four shots each path needs for a valid
  cut, per the Owner instruction to produce the minimum necessary new calls.
  The canonical script keeps its full shot count; only acceptance media is
  trimmed.
- Director runtime facts: 18 turns, 10 bound to
  `langgraph:1.2.11:director-runtime-state-v1`; every AUTO authorization
  produced exactly one canonical NodeRun and then waited on production facts.
  A proposal-bound turn is decided through the canonical Proposal API, which
  alone resumed the bound engine to `completed`; the runtime decision endpoint
  correctly refused it with `DIRECTOR_PROPOSAL_DECISION_REQUIRED`. Detached
  Shot suggestion turns were decided through the versioned runtime endpoint and
  created zero NodeRuns.
- Deliveries: template cut 19.239 s, MP4 SHA-256
  `5a14cb93b2a2d52c0dda03bfa456dd9910a8cfaa0feebb99a1984daa26b7f67b` with a
  4-cue SRT; Free cut 19.239 s, MP4 SHA-256
  `942b026c88d7d104015c50cd8685eb351cbd9a8f1e35f9a5d7d1f966df2a68d9` with a
  3-cue SRT. ffprobe confirmed H.264 video, AAC audio, MP4 container, burned
  subtitles, dialogue audio, applied timeline edits and matching duration for
  both. Both downloaded files hashed to the recorded artifact hashes.
- Editing-only change: remote image/video ProviderOperation counts were 8
  before and 8 after the rerender, so subtitle/timeline edits created no new
  billable media generation.
- DeepSeek was actually exercised through LiteLLM six times as
  `anthropic/deepseek-v4-flash`: four invocations completed with valid structured
  output and two were truthfully rejected as `INVALID_DIRECTOR_TEXT_OUTPUT`.
  All six proxy requests returned; no unknown submission remains and no retry is
  needed for this acceptance.
- The retained database had 27 successful ProviderOperations and 67 terminal
  NodeRuns (66 completed, one cached). It also had eight bound Turns still at
  `awaiting_execution / production_fact`. This is the evidence that triggered
  correction `4e61d6f`; the real MP4/SRT artifacts and hashes above are unchanged.
- The correction projects only fields allowed by `ExecutionFact`, refuses
  out-of-order Formal notices until `confirm_candidate`, and uses the existing
  low-rate worker to enqueue any missed terminal/Formal fact with deterministic
  dedupe and revision fencing. The focused real PostgreSQL flow reaches
  `candidate_confirmed` without creating another NodeRun.
- PR #79 is merged. No production deployment or release image publication was
  performed. The later correction requires a follow-up review before the final
  merged source can be called complete.
- The six Owner inputs remain byte-for-byte at their original paths. They are
  listed only in this repository's local `.git/info/exclude`, which is the
  correct Git mechanism for local inputs that must never be committed. Their
  sizes and hashes are recorded in
  `tmp/v1-d8-owner-input-local-exclude-20260911.json`. With the inputs preserved
  and excluded, the unchanged guardrail accepted a real `STARTED` event for
  `v1-d8-runtime-terminal-reconciliation-20260911`; no lifecycle status was
  forged or backdated.
