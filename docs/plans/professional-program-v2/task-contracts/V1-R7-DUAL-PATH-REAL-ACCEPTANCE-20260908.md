# V1 R7 — Real dual-path acceptance and candidate identity

**Task:** `v1-r7-dual-path-real-acceptance-20260908`\
**Parent:** G7A / G7B / G7D / R7\
**Status:** IN PROGRESS\
**Baseline:** `dev@8d2be51` (runtime implementation verified at `af4a0d8`)

## Authority, authorization, and current evidence

Owner revision 2026-09-07 §11 R7 and the current Goal authorize necessary real
text/image/video calls for both paths and final candidate Golden (Goal reference
§12). Reuse existing configured credentials/models and minimize calls; no new
subscription or unrelated spend. Unknown/already-charged submits must not replay.
Candidate/Formal/Repair/Save/Export remain explicit tested user business gates.
The seven-plan precedence, canonical single runtime and no fallback remain.

R1–R6 code and scoped/exact-source gates are recorded. Existing Golden script
still imports the same fixed fixture into both projects and predates real text
Director and SRT delivery. It is evidence tooling, not proof of R7's revised
interaction requirements. Existing 8080 services are still the September 6
acceptance image and the database is at 0055. Read-only preflight found 26 queued
and one running NodeRun. Do not replace these services, migrate their database,
flush queues, or cancel their tasks merely to obtain a clean candidate.

## Outcome

- Build exact OCI-revision API/Worker/frontend images and run a private local
  acceptance stack with its own PostgreSQL/Redis/MinIO state. Preflight may use
  loopback 8088 while the current 8080 stack remains active. Final 8080 identity/
  health evidence is a distinct gate and must not be claimed from 8088.
- Copy only the authorized account's workspace/provider configuration into the
  new isolated database or configure it through existing APIs. Do not copy live
  NodeRuns, Outbox, sessions, Artifacts or other project contents that could
  resubmit work. No secret or raw credential appears in logs/evidence/Git.
- Create distinct Template+AUTO and Free+ASSIST projects with the same canonical
  services. Template starts from a real model Story proposal; Free starts from
  explicit import/manual input. Record accepted/rejected/modified operations,
  saved versions, real Shot/Editing text turns and MANUAL suppression.
- Run minimal multiple-shot real keyframe/video chains, explicit Formal gates,
  result checkpoint readback, review annotation/Repair, and real EditSession
  MP4/SRT delivery. Reuse valid results for recovery/edit verification; preserve
  failed attempts and original Formal media until explicit replacement.
- Verify configured model/binding/reference identities without silent fallback.
  Use Agnes image + MiniMax video if a valid combination exists; otherwise mark
  that special combination NOT_VERIFIED (or blocked if an explicit release gate).
- Save sanitized, restartable checkpoint evidence for both paths, including
  exact source/images/migration, calls and known/unknown cost, Artifact hashes,
  decisions, RLS/CSRF/version negatives and MP4/SRT lineage under stable docs.

## Owned paths

- `scripts/prove_v1_current_head_golden.py` or a bounded R7 acceptance driver
- `scripts/prepare_v1_acceptance_runtime.py` if reusable safe setup is needed
- focused tests for evidence filtering/idempotent checkpoint replay
- `frontend/playwright.r7.config.ts` and `frontend/tests/live/` for the formal
  non-mock 8080 browser proof (excluded from the ordinary mock E2E suite)
- bounded product fixes only after documenting a discovered failed acceptance
  path and its source authority in this contract (not a broad runtime rewrite)
- sanitized `docs/reviews/evidence/v1-r7-current/` and candidate report
- this contract and Goal status
- ignored `tmp/r7-acceptance/` for private setup/config/checkpoints (never Git)

## Required verification and completion

1. Template+AUTO and Free+ASSIST each have real distinct project/Shot/text/media
   identities, explicit user decisions and the same NodeRun/Editing runtime.
2. Actual configured Story/Shot/Editing text calls are linked to persisted turns
   and output/context hashes; rejected operations cannot apply or regenerate.
3. Both paths reach multiple-shot 15–30 second playable H264/AAC Final Film with
   voice/burned subtitles and matching independent SRT from frozen Timeline.
4. Review/Repair and at least one real remote task's durable recovery are proven
   without an extra paid create. Editing-only rerender creates zero media calls.
5. Candidate exact source/OCI labels/migration/health and browser DOM/network/
   interaction assertions are captured. 8088 evidence alone is not 8080 PASS.
6. Provider-specific unsupported/unconfigured cases remain explicit and never
   become another provider's success. Cost unknown is not reported as free.
7. Evidence is redacted and committed, source/image binding audited; R8 CI,
   security, release candidate and Owner-only merge remain separate. The existing
   root-ledger registration issue stays visible until legitimately resolved.

## Preflight and discovered-gap progress

- Private stack `dramaforge-r7-acceptance` is initialized at 0060 on loopback
  8088, with exact preflight images built from `fa164e0`. The original 8080 stack
  and its live work are unchanged. The private config copy has one workspace,
  two verified Agnes bindings, one encrypted credential, and zero NodeRuns/
  Artifacts/Outbox copied. Secret rows flowed in memory only, never to logs/Git.
- Live read-only registry preflight confirms configured `litellm/script-quality`
  and Agnes image/video; MiniMax and Seedance are unconfigured. The private
  LiteLLM aliases point to configured DeepSeek and have no mock response. No paid
  call has yet been made. The original model identities are not relabeled.
- Separate Template+AUTO and Free+ASSIST projects and an explicit workspace text
  profile have been created through the new API. Checkpoints are kept in
  `tmp/r7-acceptance/acceptance.json`; setup facts in `api-preflight.json` and
  `config-copy-result.json`.
- `scripts/prove_v1_r7_acceptance.py` records a durable checkpoint before each
  write; unknown outcomes cannot replay, completed steps restore responses,
  evidence removes secrets/signed query strings, and paid phases require both
  --real and a health-verified exact --candidate source (never app_env=test).
  Safety unit tests cover redaction, no-call opt-in and replay/unknown handling.
- R7 preflight exposed the local-only Editing rejection gap. Bounded fix
  `V1-R7A-EDITING-REJECTION-20260908.md` now wires canonical durable rejection.
  This is an acceptance-driven fix, not permission to rewrite the editing runtime.
  Rebuild only the private stack before real calls; other tasks remain untouched.
- The driver explicitly leaves review/Repair, real remote recovery, browser UI,
  Editing-advice application and MP4/SRT download as NOT_VERIFIED until their
  actual evidence is collected. A primary chain alone cannot set complete=true.

- Capability preflight found the verified current Agnes bindings are portrait
  (9:16). The initial 16:9 empty scaffold projects are retained as preflight
  artifacts, not relabeled. Real acceptance will use separately created 9:16
  projects/checkpoints; no model or aspect fallback is performed after a paid
  request. The original two empty projects produced zero Provider/NodeRun rows.

## Acceptance-driven follow-up progress

- The portrait preflight completed 72 checkpointed API steps on `fe203c1`: a
  real Template Story call, real Template/Free Shot calls, five and four distinct
  Shot image/video chains, and explicit Formal decisions. All paid steps have a
  durable successful receipt; none is replayed after the later source change.
- Final Film preparation exposed a duplicate local TTS Artifact hash. The
  bounded audio-only reuse fix is committed at `0e45207`; the preserved failed
  run has `WORKER_ERROR`, while its retry on the updated isolated stack is
  `cached` and the dependent composite/continuity runs complete with zero new
  image/video operation. The original failed rows remain in history.
- The Template preflight now has a playable 24.027-second MP4 and independent
  SRT. The Free preflight has a real Editing text turn and a playable
  19.239-second MP4/SRT. These mixed-source bug-finding results are deliberately
  not relabeled as final same-candidate evidence.
- The first Editing driver requested a real suggestion but then overwrote the
  draft with its own fixture values. The driver now applies the returned typed
  operations to a local draft first, records adoption metadata, and only then
  performs the explicit Timeline save. Focused no-network tests cover adoption,
  fail-closed targets, redaction, opt-in and unknown/replay behavior.
- The driver now has bounded review-submit/review-collect, MANUAL and negative
  regressions, editing-only rerender, delivery download/hash and external
  recovery/browser/runtime proof imports. The live Playwright proof targets the
  real gateway and projects with no API mocks. Final proof still requires a new
  clean candidate, one Review Repair remote task interrupted after durable
  submit and recovered after Worker restart, both current-candidate films, and
  formal 8080 identity/browser evidence.
