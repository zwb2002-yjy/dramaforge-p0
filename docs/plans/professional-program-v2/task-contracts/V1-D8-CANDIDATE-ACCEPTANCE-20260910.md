# V1-D8-CANDIDATE-ACCEPTANCE-20260910

Status: IN_PROGRESS, local candidate evidence only.

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
| MANUAL, Director stopped | LOCAL PASS | Empty project through playable MP4/SRT, zero Director rows and zero source regeneration on rerender |
| Free + ASSIST | LOCAL CONTROLLED PASS | Real typed Story/Shot/Editing proposals and partial decisions are product-accessible; the manual production controls complete independently; the server rejects a new AUTO delegation grant; candidate-bound real text/media run was not repeated in this local no-paid run |
| Template + AUTO | LOCAL CONTROLLED PASS | Product UI/API freezes the exact plan, persists a one-shot grant and accepted decision, then an independent Director worker creates exactly one canonical NodeRun and waits on production facts; retry reuses the Turn/wakeup; candidate-bound real text/media run was not repeated in this local no-paid run |
| Source/image/runtime identity | DIRTY-TREE VERIFIED, NOT COMMITTED | A corrected 796-file manifest now matches both freshly built quality images byte-for-byte after a full Gate pass; the earlier claimed digests were stale and are withdrawn. Requires a reviewed commit and a rebuild from that commit |
| Release/Owner merge | NOT AUTHORIZED | No commit, push, PR, merge or deploy was performed |

Completion-criterion audit against Owner design §12:

| Criterion | Current evidence | Local result |
|---|---|---|
| Production independent of Director | Empty MANUAL project reaches the canonical Final Film worker with zero Turn/control/wakeup rows | PASS |
| One production kernel | Manual and delegated commands both enter `ProductionCommands` and the same NodeRun/Outbox/Arq/ProviderOperation/Artifact chain | PASS |
| Recoverable Director | PostgreSQL checkpoints survive connection/process replacement; Inbox/wakeup and committed signals resume once | PASS |
| Replayable side effects | Stable authorization/receipt plus invocation unknown-submission rules prevent a second model/media create | PASS |
| Fresh context Gate | Shot/profile versions, revoke races, MANUAL changes, fencing and RLS reject stale/cross-scope actions | PASS |
| One domain truth | SDK state stores flow position/receipts only; Proposal, Formal, NodeRun, Artifact and Export remain canonical records | PASS |
| Replaceable engine boundary | Application contracts contain no LangGraph/private SDK types; engine routing is immutable per Turn | PASS |
| Product behavior | AUTO delegation, ASSIST decisions, independent manual controls, Review/Repair/Editing and MP4/SRT paths pass controlled regression | PASS |
| Trustworthy current candidate | The corrected 796-file manifest matches both quality images byte-for-byte after a full Gate pass, but the source is still uncommitted and the real text/media run is absent | NOT COMPLETE |

The candidate cannot be marked COMPLETE from this dirty working tree. Final D8
completion requires the prepared changes to be reviewed and committed, then the
AUTO/ASSIST real-provider acceptance to run against that exact source/image.
Those calls can incur cost and were not made during this local implementation.
