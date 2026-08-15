# Release Gate Board

**Status:** LIVE / evidence tracker, not a product contract

**Last reviewed:** 2026-08-13

## How To Use This Board

This board operationalizes the release requirements in
[`../current/01-产品与发布契约.md`](../current/01-产品与发布契约.md),
[`../current/03-质量与验证体系.md`](../current/03-质量与验证体系.md), and
[`../current/04-执行路线图.md`](../current/04-执行路线图.md). Those contracts
remain authoritative when this board and a contract disagree.

Each entry is `OPEN` until evidence is attached to one clean candidate commit.
Use `PARTIAL` only when some required evidence exists but the release criterion
is still open. `PASS` requires the evidence described in the row; no
automation, API mock, historical P0 evidence, or manual assertion may replace
an evidence type explicitly marked real-provider, target-user, or installation.

Generated, source-bound evidence belongs under
`tmp/p0-evidence/<source-commit>/`; do not put prompts, credentials, permanent
object URLs, download grants, or participant identities in this repository.
Run [`real-provider-evidence-preflight.md`](real-provider-evidence-preflight.md)
before each real Provider submission; that runbook does not itself authorize
spend.

## Current Candidate Boundary

| Field | Value |
|---|---|
| Candidate source commit | `0cb923f6b483bb957a9ec383fb5d2a5b85b84b54` (`codex/director-v1-candidate`) |
| Candidate state | Clean isolated worktree used for the recorded A2 live-stack scenario. The shared development worktree remains intentionally dirty with pre-existing untracked material and is not the candidate boundary. |
| Automated baseline | Candidate checks passed: backend `ruff`, `mypy app`, and `pytest` (`605 passed`); frontend lint, typecheck, Vitest (`46 passed`), focused Playwright (`5 passed`), and production build; `git diff --check`. Details are recorded in `docs/开发执行检查点.md`. |
| Evidence limitation | A2 has source-bound, isolated live-stack edit-then-cross-mode evidence, including static batch and unused-reservation lineage, without Provider activity. No real Provider call, user study, installation test, or Q0-Q6 release evidence has been collected. |

## Gate A: Core Experience (Due 2026-08-31)

| ID | Requirement | Evidence Required | Status | Next Action |
|---|---|---|---|---|
| A1 | Three entries, four stages, four confirmations, and change preview | Source-bound browser E2E against the candidate plus backend command evidence | PARTIAL | Replace mocked-only E2E with a controlled live-stack scenario after a clean candidate exists. |
| A2 | Quick and professional modes share one project truth | Browser/API scenario that edits, reads, and verifies the same version and batch lineage in both modes | PASS | `0cb923f` records an authenticated isolated PostgreSQL/API/Vite scenario: Quick shows structured impact for a locked StoryCore edit with one accepted static batch and one unused CNY reservation, restricts action to explicit confirmation, and Professional reads the identical revision-2 StoryCore plus `superseded_by_change` batch and `released` reservation. The scenario has zero page/console errors, external Provider requests, NodeRuns, ProviderOperations, and media Artifacts. |
| A3 | Trial, production, and repair spend are authorized | Real provider run with authorization, effective request, reservation, actual cost, and no unapproved paid call | OPEN | Run the real-Provider evidence preflight, obtain per-run written approval, then capture the full ledger evidence. |
| A4 | Canonical and required media parameters enter the effective request | Spy contract test plus real request evidence for the selected binding | PARTIAL | The zero-network Unified Provider Spy verifies Canonical/first-frame lineage, aspect ratio, duration, native-audio flag, frozen binding, and persisted sanitized summary; after preflight, run the selected Provider path on a clean candidate. |
| A5 | Representative trial reveals a known risk or supports continuation | Trial artifact, Q0-Q6 report, limitations, and recorded user decision | OPEN | Select a high-information dialogue shot and run it after cost authorization. |
| A6 | One failed shot is repaired locally | Intentional failure, repair option, extra authorization, rerun scope, reused artifacts, and final evidence | OPEN | Exercise this during the first real production run. |
| A7 | 15-30 second Chinese dialogue work and four deliverables export | Real multi-shot run: `program.mp4`, `subtitles.srt`, `timeline.json`, package hash, and project summary | OPEN | Run the frozen golden sample after A3-A5 are ready. |
| A8 | Three target users finish without developer intervention | Three redacted participant records using `unmoderated-user-test.md` | OPEN | Recruit and schedule three sessions; developers observe only. |
| A9 | At least two users want to save, show, publish, or make another work | Redacted post-session responses tied to A8 participants | OPEN | Ask the closing questions verbatim after each session. |

## Quality And Evidence Gate

| ID | Requirement | Evidence Required | Status | Next Action |
|---|---|---|---|---|
| Q0 | Authorization, capability, license, and reference validity | Preflight decision, binding evidence, license inventory, and budget record | OPEN | Use the real-Provider evidence preflight to freeze selected model/weight/voice inventory before an authorized paid test. |
| Q1 | Effective request completeness | Sanitized effective request and TranslationReport; Canonical artifact hash and injection location | PARTIAL | Automated Spy coverage proves the compiled request and persisted sanitized summary retain the required Director fields. After preflight, capture the selected Provider's real request evidence on a clean candidate. |
| Q2 | Artifact integrity | Decode, dimensions, duration, audio, black-frame/silence checks and hashes | OPEN | Run against trial and final delivery artifacts. |
| Q3 | Identity, appearance, and temporal evidence | Canonical/request/artifact lineage, frame observations, coverage/limitations, and human conclusion | OPEN | Complete `character-consistency-v1` with audited human trial acceptance; no automatic similarity threshold is a release gate. |
| Q4 | Voice, speaker, lip-sync, and performance evidence | Audio/lip-sync observations, limitations, and human conclusion | OPEN | Capture on the representative dialogue shot. |
| Q5 | Narrative and continuity evidence | Storyboard-to-output review, dialogue checks, continuity evidence, and human conclusion | OPEN | Review trial and full work with the quality report. |
| Q6 | User acceptance and subjective overrides | Trial/final user decisions and, where used, retained override reasons | OPEN | Collect through the workflow and user-study records. |
| Q7 | Three repair diagnoses | One identity drift, one voice/lip-sync, and one narrative issue with targeted repair evidence | OPEN | Plan and execute only after each issue has real evidence. |
| Q8 | Model/weight license traceability | Third-party inventory, sources, license compatibility review, and known limits | OPEN | Complete the release inventory and Owner sign-off. |

## Gate B: Offline Production Stack (Due 2026-09-06)

| ID | Requirement | Evidence Required | Status | Next Action |
|---|---|---|---|---|
| B1 | One documented offline stack completes a real work | Hardware, versions, licenses, timings, peak memory/disk, restart recovery, final artifacts | OPEN | Freeze a candidate stack after the cloud workflow Gate A is stable. |
| B2 | Offline limitations are explicit | Comparison of quality/capability gaps and supported fallback boundary | OPEN | Publish only measured limits; do not infer parity with cloud providers. |

## Gate C: Installation And Release (Due 2026-09-15)

| ID | Requirement | Evidence Required | Status | Next Action |
|---|---|---|---|---|
| C1 | Linux/AIOS first-class installation | Clean install, real workflow, restart, backup/restore, upgrade, and support-matrix record | OPEN | Execute the deployment runbook on declared hardware. |
| C2 | Windows 11 first-class installation | Clean Docker Desktop/WSL2 install, real workflow, download, restart, and support-matrix record | OPEN | Execute after Gate A candidate freezes. |
| C3 | macOS second-class installation | Compose/UI/cloud-provider verification and explicit local-model limitation | OPEN | Execute cloud path only; document unsupported local features. |
| C4 | Security, privacy, and supply-chain release checks | Single Owner behavior, secret/log/download boundary, SBOM/vulnerability review, third-party inventory | OPEN | Run security workflow and complete owner review. |
| C5 | Release candidate is reproducible | All release evidence refers to one clean commit; install, automated tests, real-provider, offline, and browser evidence agree | OPEN | Freeze the final candidate only after A-C evidence is complete. |

## Gate Review Record

For every status change, append a redacted entry here. A `PASS` entry must name
the exact clean source commit, evidence directory, reviewer, date, and any
remaining known limits. Do not delete or rewrite a failed or blocked entry.

| Date | Gate IDs | From -> To | Source Commit | Evidence Location | Reviewer | Notes |
|---|---|---|---|---|---|---|
| 2026-08-13 | A2 | OPEN -> PARTIAL | Dirty worktree; no candidate commit | Local unit/build evidence; `docs/task-contracts/director-shared-workspace-evidence.md` | Development self-check | Backend snapshot lineage and mocked professional-mode rendering are covered. This is not source-bound live-stack, real-provider, or release evidence. |
| 2026-08-13 | A2 | PARTIAL -> PARTIAL | `712399f06db23cbdc63a9a6ea6572d4c136f1ed7` | `tmp/p0-evidence/712399f06db23cbdc63a9a6ea6572d4c136f1ed7/a2-live-stack.json` | Development self-check | Clean isolated PostgreSQL/API/Vite scenario logged in and read the same workflow, locked storyboard revision 3, trial batch, and CNY reservation in Quick and professional modes. Four Quick stages and Director handoff rendered; legacy import/shot/export controls, post-login page/console errors, Provider requests, NodeRuns, ProviderOperations, and media Artifacts were all absent. The scenario was read-only because the seeded `trial_running` state does not allow `propose_change`; a legal edit-then-cross-mode case remains required. No Provider call or spend occurred. |
| 2026-08-13 | A2 | PARTIAL -> PARTIAL | `602f536d35d9de8b508f65b42d380be3d51573d2` | `tmp/p0-evidence/602f536d35d9de8b508f65b42d380be3d51573d2/a2-live-stack.json` | Development self-check | Clean isolated PostgreSQL/API/Vite scenario authenticated an Owner, created a legal locked creative state, used Quick to propose a StoryCore change, displayed exactly three invalidated downstream versions, restricted actions to `confirm_change`, explicitly confirmed revision 2, and then read the identical StoryCore ID/revision through Professional. Page errors, console errors, external Provider requests, NodeRuns, ProviderOperations, and media Artifacts were all zero. This does not close A2 because that editable state intentionally has no existing batch/reservation lineage; no unsafe media-state edit behavior was introduced. No Provider call or spend occurred. |
| 2026-08-13 | A2 | PARTIAL -> PASS | `0cb923f6b483bb957a9ec383fb5d2a5b85b84b54` | `tmp/p0-evidence/0cb923f6b483bb957a9ec383fb5d2a5b85b84b54/a2-live-stack.json` (SHA-256 `f034d618dd27125788105e30f7b4a0ef2ed918f950378dbca6182c0a9d5f1876`) | Development self-check | Clean isolated PostgreSQL/API/Vite scenario verified exact candidate source through `/health`, authenticated an Owner, inserted one local-only accepted static trial batch and one unused CNY reservation, then used Quick to preview and explicitly confirm a StoryCore revision. Professional read the same StoryCore ID/revision 2, `trial/superseded_by_change`, and `released/3.000000 CNY`; the database also verified revoked authorization and invalidated approvals. Post-login page/console errors, external Provider requests, NodeRuns, ProviderOperations, and media Artifacts were all zero. No Provider call, paid operation, worker, dispatcher, or media materialization occurred. This A2 result does not satisfy any real-provider, user-study, offline-stack, installation, quality, or release gate. |
| — | — | — | — | — | — | No source-bound Gate decision recorded yet. |
