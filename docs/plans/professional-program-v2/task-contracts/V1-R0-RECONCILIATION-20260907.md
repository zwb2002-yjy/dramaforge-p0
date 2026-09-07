# V1 R0 — Baseline reconciliation and evidence recalculation

**Task:** `v1-r0-reconciliation-20260907`\
**Parent:** G0 / G7E / G8\
**Status:** COMPLETE\
**Baseline:** `dev@15a0b41338d51eeb2da162180869f45291fd5aef`

## Problem and outcome

The 2026-09-07 Owner revision requires implementation from current repository
facts. Historical blockers cannot be treated as missing code, and historical
Golden/Release evidence cannot be relabelled as current acceptance. R0 registers
the revision, reconciles source, runtime, database and remote checks, and assigns
every remaining requirement to R1–R8.

## Current evidence

- Local `dev` was safely fast-forwarded from `d024b2d` to the fetched remote
  `15a0b413`; the only pre-existing worktree entries were two unrelated,
  user-owned untracked Markdown files, which remain untouched.
- GitHub Actions at `15a0b413`: CI `34054711617` PASS, Security `34054711552`
  PASS, Release `34054711575` SKIPPED.
- The running API, dispatcher and both Workers share backend image
  `sha256:2dad34d024b5c910a19a5155be5b518559b01e4bb52c1f3938421facbfb9382a`;
  the frontend uses
  `sha256:eb25c82425b7a068367f3ae047d6c067a11e8979b20804c71502044774b47376`.
  All carry revision `worktree-acceptance-20260906-32216450fd43`, so the live
  8080 environment is healthy but is not the current clean candidate.
- Application and database migration heads both report `20260903_0055`.
- Read-only 8080 inspection recovered an existing Free+ASSIST project, three
  Formal keyframes/videos, EditSession v2, and an available playable/downloadable
  Final Film MP4. No final-Timeline SRT download is exposed.
- Static source inspection proves the first development gaps: Scene workspace
  has no active-run polling; changing the selected Shot clears dirty/suggestion
  draft state; Shot/Editing recommendation paths default to deterministic
  transports; shot-scoped Assistant context attempts to load a Scene by Shot ID;
  and Final Film persists only the MP4 ExportItem.

## Owned paths

- `docs/plans/professional-program-v2/README.md`
- `docs/plans/professional-program-v2/v1-goal/DramaForge_V1_设计方案_20260907.md`
- `docs/plans/professional-program-v2/v1-goal/DramaForge_V1_实施方案_20260907_修订版.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `docs/reviews/V1-RECONCILIATION-20260907.md`
- this contract

## Invariants and non-scope

- No product runtime, migration, Provider request, paid generation, production
  write, deployment, release trigger, or historical evidence mutation.
- Preserve the seven source plans and their integrity hashes.
- Preserve the two pre-existing untracked user documents.
- A healthy historical runtime is recorded as reusable evidence, not as a
  current-head PASS.

## Acceptance and result

- The two Owner documents are registered with content-preserving Git line-ending
  and Markdown hard-break normalization, then linked from the authority index:
  PASS.
- Source, remote checks, runtime images, migration and a read-only existing
  project flow are individually identified: PASS.
- Each G7E item and R1–R8 dependency has a concrete evidence state and owning
  task in `docs/reviews/V1-RECONCILIATION-20260907.md`: PASS.
- Goal status remains blocked until R1–R8 and same-candidate gates complete:
  PASS (no premature completion claim).

## Next

R1 is the first dependency-ready implementation task. R5 may gather additional
evidence in parallel only if it does not overlap R1 paths; the default execution
remains serial.
