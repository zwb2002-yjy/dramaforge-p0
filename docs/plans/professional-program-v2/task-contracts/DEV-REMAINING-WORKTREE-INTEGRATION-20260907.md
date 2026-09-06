# Task: Integrate all remaining approved work into dev

## Owner authority and outcome

- Current request: “都合进dev”, received after the acceptance repairs were merged through PR #12. This authorizes the remaining existing navigation and Agent-instruction edits to be committed and pushed to dev, not another main merge.
- This task does not authorize vNext implementation, Dependabot upgrades, new dependencies, model fees, production writes, new deployment, release tags or publication dispatch.
- Preserve the existing seven-plan source order and the two bounded contracts: navigation IA and Agent instruction optimization. Their previous no-commit/no-push restrictions described earlier turns; the current Owner request authorizes only their Git integration and required validation.
- Baseline dev `6a269f2`; main `4cae136`. Main's code tree was identical, so dev was safely fast-forwarded to the main merge commit without changing any working file.
- Outcome: all 32 initially outstanding repository paths are included in separately reviewable instruction/navigation commits; current dev is pushed, exact-head checks pass, and the tracked/untracked worktree is clean. Ignored runtime/evidence/credentials and the external global instruction file remain outside Git.

## Scope / owned paths

- `.agents/AGENTS.md`
- `AGENTS.md`
- `AGENT_EXECUTION_PROTOCOL.md`
- `CLAUDE.md`
- `agent.md`
- `docs/plans/professional-program-v2/README.md`
- `docs/plans/professional-program-v2/navigation-ia/DramaForge_统一导航与项目大厅信息架构设计方案.md`
- `docs/plans/professional-program-v2/navigation-ia/DramaForge_统一导航与项目大厅执行方案.md`
- `docs/plans/professional-program-v2/task-contracts/AGENT-INSTRUCTION-OPTIMIZATION-20260905.md`
- `docs/plans/professional-program-v2/task-contracts/V2-UNIFIED-NAVIGATION-AND-PROJECT-LOBBY-20260904.md`
- `docs/runbooks/agent-instructions/execution-protocol-reference.md`
- `docs/runbooks/agent-instructions/v1-goal-reference.md`
- `frontend/src/components/workstation/ProjectLobbyShell.tsx`
- `frontend/src/components/workstation/ProjectWorkspaceShell.tsx`
- `frontend/src/components/workstation/WorkstationShell.tsx`
- `frontend/src/components/workstation/navigation-shell.css`
- `frontend/src/components/workstation/project-shell-visual.css`
- `frontend/src/components/workstation/project-shell.css`
- `frontend/src/features/review/ReviewWorkspace.tsx`
- `frontend/src/routeTree.gen.ts`
- `frontend/src/routes/design-preview-page.tsx`
- `frontend/src/routes/index.tsx`
- `frontend/src/routes/pages.ts`
- `frontend/src/routes/production-page.tsx`
- `frontend/src/routes/projects.$projectId.tsx`
- `frontend/src/routes/settings-page.tsx`
- `frontend/src/routes/settings.tsx`
- `frontend/tests/e2e/navigation-ia.spec.ts`
- `frontend/tests/e2e/professional-manual.spec.ts`
- `frontend/tests/e2e/professional-mocks.ts`
- `frontend/tests/e2e/smoke.spec.ts`
- `frontend/tests/unit/WorkstationShell.test.tsx`

- This integration contract and task-local evidence under `tmp/dev-integration-20260907/`.

## Validation

- Instruction-only group: compare preserved reference payloads with the original Git source, preserve image/evidence rules, resolve relative links, run directory compliance and diff checks. No model forward-test is claimed.
- Combined navigation/repair frontend: typecheck, lint, formatting, unit, API check, build, full E2E, navigation/entry/dirty/candidate/formal regressions and required responsive checks.
- Reuse the existing in-app browser for read-only current-runtime L1/L2/Lobby/Settings checks. Record runtime/source identity equivalence; do not relabel the existing worktree image as a clean-commit release.
- Push dev once both groups are committed; require the exact-head CI and Security. Existing backend content is unchanged, but the repository's normal full container gate still runs remotely.
- Preserve all initial file contents other than bounded contract closeout annotations or genuinely required gate fixes. No force push, stash, reset, cleanup, main push/merge, or protection bypass.

## Lifecycle and completion boundary

At entry the root-clean ledger guard is unsatisfied because the remaining Owner-approved changes are uncommitted. Do not forge an earlier STARTED event. Once the authorized commits make the root clean, record the actual current closeout/verification stage through the existing control tool if its validations permit. Completion of this dev-integration request is distinct from vNext, a paid Golden, formal release/deployment or the whole original acceptance Goal.

## Current evidence

- `tmp/dev-integration-20260907/preservation-before.json`: all 32 initial paths backed up, including the deliberate ProjectLobbyShell deletion.
- `tmp/dev-integration-20260907/instruction-static-checks.json`: reference sources, image rules, links and protected-path assertions.
- Current selected-source test logs and exact-head CI evidence will be recorded in this task-local directory; do not reuse a prior branch's pass as a new-head result.

## Submission formatting correction

The two new navigation documents used six Markdown hard breaks expressed as trailing double spaces. Those six metadata-line breaks are now expressed as explicit backslash hard breaks, preserving their wording, order and rendered separation while satisfying the staged whitespace gate. No seven-plan source or product decision is changed.

## Local selected-source gate

- Selected source tree `1032e7255da89cc2696793d07b2661f5924a3eeb`: frontend typecheck, lint, formatting, API check, build, 134 unit tests and all 17 browser E2E tests PASS. Only closeout documentation is added after this source test.
- All 337 frontend/backend application files match the existing verified acceptance-runtime source after Git LF normalization. Read-only in-app checks passed for the existing Editing L1/L2 at 319px, Project Lobby separation and Settings context at 1280px. The task-only QA tab was closed, original tabs retained. No live creative write, model call or deployment was performed.
- Directory compliance passes on the selected source archive. Running it at the original root encountered an inaccessible historical `.worktrees/.../backend/.venv/lib64` link; that pre-existing ignored resource was not deleted or altered. Exact-commit remote CI must still execute the normal repository gate in its clean checkout.
- Evidence: `frontend-results.json`, `selected-directory-compliance.log`, `instruction-static-checks.json`, `runtime-source-equivalence.json`, `in-app-browser-evidence.json` in `tmp/dev-integration-20260907/`.
