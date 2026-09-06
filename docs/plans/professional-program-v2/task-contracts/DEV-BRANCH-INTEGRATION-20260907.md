# Task: Integrate the remaining 20 branches into dev, then delete them

## Authority / scope

- Owner request: “合并进dev然后删除呀”, following the explicit inventory of one unmerged historical-evidence branch and 19 Dependabot PR branches.
- This authorizes the listed dependency/toolchain updates, necessary compatibility and lockfile reconciliation, their checked integration into dev, then deletion of the integrated source refs. It does not authorize a main update, live deployment, paid calls, production data writes, vNext features, force pushes, history rewriting or weakening tests/security checks.
- Follow the current professional-program-v2 authority and execution protocol. No product plan is replaced. Preserve canonical creative/execution identity, explicit apply/save/Formal/export gates and no silent model fallback.
- Root dev baseline: `d024b2d2ee23ea6e31ad08b99bbb2403a59fdbaf`. Root dev and the running acceptance deployment remain untouched during isolated integration.
- Worktree: `.worktrees/dev-branch-integration-20260907`; branch: `agent/dev-branch-integration-20260907`, created through the repository script. The final integration PR targets dev and must satisfy normal branch policy and complete exact-head CI/Security. Never self-approve a review or use an administrator bypass.

## Source identities

- `agent/release-evidence-720bde4` — `1b2a6a2c129bfa09e9fcc0ec1ce971aab216d6d3`
- `dependabot/npm_and_yarn/frontend/typescript-7.0.2` — `5c3612db02058e34a378f88ec3c6861d4f9fa3db` (PR #64)
- `dependabot/npm_and_yarn/frontend/typescript-eslint-8.69.0` — `dfbd1671dd557ce92b13b5d9cf2b15bb796e4239` (PR #63)
- `dependabot/pip/backend/asyncpg-gte-0.30.0-and-lt-0.32` — `8949e4aa36ee8fb31bf7b0e00fb7613ac288e39b` (PR #62)
- `dependabot/pip/backend/numpy-gte-1.26.0-and-lt-3` — `777b3dba88edad953560ce1872ffc37e6ca37485` (PR #61)
- `dependabot/npm_and_yarn/frontend/tanstack/react-router-1.170.32` — `395d0b50df29a7da296a392c5aeac45b49e4c14e` (PR #60)
- `dependabot/npm_and_yarn/frontend/zustand-5.0.15` — `5894823a358e4632ee4e8431159407d0e1064d67` (PR #59)
- `dependabot/pip/backend/ruff-gte-0.8.0-and-lt-0.17` — `3b3bad1fc2cb7c34d7c86f7bef979c2ff0382cc7` (PR #58)
- `dependabot/npm_and_yarn/frontend/testing-library/react-16.3.3` — `f53caec84a3141f9b68c847e7ae4a57a3dba0055` (PR #57)
- `dependabot/pip/backend/arq-gte-0.26.0-and-lt-0.29` — `0f61c5bd26fcf151b307afcb25db1ea2da178d5f` (PR #56)
- `dependabot/github_actions/actions/upload-artifact-7` — `26a6dcda18146c364982178a00437eb1dd26a373` (PR #55)
- `dependabot/pip/backend/mypy-gte-1.13.0-and-lt-3` — `7f08f26a9b0e121e68461629ffb5a89990d66fd6` (PR #54)
- `dependabot/pip/backend/uvicorn-gte-0.32.0-and-lt-0.53` — `ca97fb92b68a6d2a892a43b94df458c3ed647b5a` (PR #53)
- `dependabot/github_actions/actions/checkout-7` — `518a5f30e1bb7cec639a2bab34ffa709136bd7f4` (PR #52)
- `dependabot/docker/frontend/nginxinc/nginx-unprivileged-1.31.5-alpine` — `47822411a93baf8135a2ef2e51b07148f2a28bcd` (PR #51)
- `dependabot/github_actions/softprops/action-gh-release-3` — `3b9805f3242c04fc7d203b11899df27899a2492f` (PR #50)
- `dependabot/github_actions/actions/attest-build-provenance-4` — `898fd742326eaf22f41009fb396efcd3cb203c87` (PR #49)
- `dependabot/github_actions/docker/setup-buildx-action-4` — `f6760a97d90beabac40838e8b6afba3b3e8e88c2` (PR #48)
- `dependabot/docker/frontend/node-26-alpine` — `10e69d7b319b6a66b9f5906547b41000decdb3b7` (PR #47)
- `dependabot/docker/backend/python-3.14-slim-bookworm` — `a13e95b67743fa460ec72e25ae5a3c549ef87c9e` (PR #46)

## Current drift and implementation boundaries

- The historical branch carries frozen 720bde4 Golden/release evidence and stale COMPLETE/READY status updates. Preserve all six source files under an explicitly historical archive, retaining their hashes and original paths; do not replace the current Goal/Task/release statuses with these older claims. Historical data is evidence, not fresh acceptance or authority.
- Python Dockerfiles target 3.14 while project metadata currently permits only 3.12. Expand supported Python versions through 3.14 and reconcile the locked environment; keep the existing minimum and static targets unless an actual compatibility check requires a documented change. Verify the quality/runtime images actually execute Python 3.14, not an implicitly downloaded 3.12 interpreter.
- TypeScript 7 removes the JavaScript compiler API consumed by existing tools. Keep native TypeScript 7 under `@typescript/native` and call its bin explicitly from every project typecheck/build command. Actual npm metadata adds a tighter constraint than the initial TypeScript-6 bridge proposal: openapi-typescript 7.13.0 requires a TypeScript ^5.x peer, so the separate JavaScript API remains TypeScript 5.9.3, satisfying both the generator and typescript-eslint. Do not let a bare legacy `tsc` executable silently replace the native 7 compiler; verify the explicit compiler reports 7.0.2. No --legacy-peer-deps or --force install is allowed.
- Reconcile all requested npm versions and the six Python requirement updates in lockfiles using project/isolated container tooling. No global runtime/dependency installation or unrelated package upgrade.
- Non-overlapping Docker/Action version changes are preserved; release-only Action upgrades receive static contract/tag/input validation, not a live publication run. No release tag or [release-candidate] trigger.
- Source branch merge parents are retained so reachability proves integration. Resolve intermediate lockfile conflicts deterministically, then generate and verify the combined exact lock before any final candidate claim.

## Owned paths

- `.github/workflows/ci.yml`
- `.github/workflows/security.yml`
- `.github/workflows/release.yml`
- `backend/Dockerfile`
- `backend/Dockerfile.quality`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/app`
- `backend/tests/unit/test_ci_workflow_contract.py`
- `backend/tests/unit/test_compose_contract.py`
- `backend/tests/unit/test_dockerfile_context.py`
- `backend/tests/unit/test_release_contract.py`
- `backend/tests/unit/test_branch_integration_contract.py`
- `frontend`
- `docs/reviews/history/720bde4`
- `docs/reviews/GOLDEN-FREE-ASSIST-FROZEN-720bde4.json`
- `docs/reviews/GOLDEN-TEMPLATE-AUTO-FROZEN-720bde4.json`
- `docs/reviews/V1-RELEASE-GATE-REPORT.md`
- `docs/plans/professional-program-v2/task-contracts/V1-G7D-DUAL-PATH-FINAL-FILM-20260903.md`
- `docs/plans/professional-program-v2/task-contracts/V1-G8-RELEASE-GATE-20260903.md`
- `docs/plans/professional-program-v2/v1-goal/GOAL-STATUS-20260903.md`
- `docs/plans/professional-program-v2/task-contracts/DEV-BRANCH-INTEGRATION-20260907.md`

- Task evidence under root `tmp/branch-integration-20260907/` (ignored, no secrets).

## Required verification

- No sensitive credentials, signed URLs or raw secret-bearing provider payloads are newly materialized in the historical archive; inspect with safe structured scans, not raw binary/screenshot dumps.
- Locked dependency sync, dependency peer coherence, native compiler and Python runtime identity checks.
- Backend full Ruff/mypy/unit plus isolated PostgreSQL migration/integration/RLS; pinned real-proxy/mock-upstream integration with no live Provider credentials.
- Frontend format/lint/typecheck, all unit/E2E, API generation consistency and production build; retain navigation, Director, Editing and Review safety assertions.
- Rebuild isolated quality images and non-publishing runtime images under task-only tags. Tests use only task-specific services, volumes and network/ports; never replace the current app or shared quality image tags.
- Full exact-head CI and Security on the integration PR and on dev after merge. No skip/timeout/assertion weakening to obtain green status. Stop for Owner clarification only for a genuinely new product/permission decision or an unsupported upgrade with no scope-preserving resolution.
- Immediately before merge/deletion, recheck source tips and protected dev/main identities. Delete only after the accepted source commits are reachable from remote dev and required checks passed; preserve any source ref that changed unexpectedly until reconciled.

## PR / cleanup facts

Use a single allowed agent/* → dev integration PR for the combined result. Retarget existing Dependabot PRs to dev for accurate indirect-merge tracking at the final integration stage, verifying that rebases have not changed the frozen source tips. Individual PR status is not a substitute for the combined candidate gate. The historical branch is included as a merge parent and archive in the same integration PR. Remove the task worktree/branch only after the integration PR is actually merged, the worktree is clean, owned test resources are terminal and evidence has been retained outside it.

## References / evidence

- Current repository Dockerfiles, package/lock files, CI/quality configuration and existing tests establish actual behavior.
- Microsoft TypeScript 7 announcement: official compiler/API coexistence guidance; npm metadata confirms typescript-eslint 8.69.0 peers >=4.8.4 <6.1.0 and @typescript/typescript6 6.0.2.
- `D:/dramaforge/tmp/branch-integration-20260907/branches.json` freezes all 20 source identities.
- This task does not claim whole-project, new paid Golden or deployment/release completion.

## Compatibility evidence refinement

An initial API-6 lock resolution emitted an incompatible OpenAPI peer warning. That candidate is not accepted. The existing generator has no released compatible API-6 peer range, so preserve its existing 5.9.3 API while keeping the requested native 7 compiler as an explicit independent command. Regenerate with strict peer checks and verify npm ci/npm ls; no peer constraint is disabled and no production model fallback is involved. The discarded intermediate resolver log remains evidence, not a passing gate.

## Security reconciliation

A fresh full npm audit exposed a high-severity Browserslist finding already present in the baseline lock (GHSA-c83g-rgw3-j3cx / GHSA-73wf-gq98-2v4g; affected <=4.28.6, fixed from 4.28.7). The lock now uses 4.28.9 within the existing parent ranges, with only its browser-database dependencies updated. Record the lock delta and require a clean final audit; do not suppress audit findings or reduce severity gates. The original failure remains evidence, not a passing gate.

## Local compatibility prechecks (not the final gate)

- Node 26.8.1 ran the explicit native compiler 7.0.2 while the generator/ESLint API reported 5.9.3. npm dependency-tree validation, frontend lint/type/format/unit/build and 17 E2E scenarios passed on the pre-security-patch quality image; rerun the final image after the Browserslist lock correction.
- Python 3.14.7 with Ruff 0.16.6 and mypy 2.3.1 passed full backend static checks (236 app source files) and five new integration-contract tests. Ruff's newly enforced UP046 required only a manual PEP-695 syntax update to PackRegistry, preserving its BaseModel bound and every method body; a regression checks highest-version selection and refusal to overwrite a mismatched contract. No rule was disabled.
- All five upgraded Actions exist at their requested tags and every supplied workflow input is accepted by their action metadata. Release-only operations remain statically checked, not published/executed.
- The first Python image metadata fetch timed out before any build step. A normal repeat pull succeeded; the requested 3.14 image was used, never a lower-version fallback.
- Final exact-commit quality images, full PostgreSQL/proxy/API gates, runtime smoke, npm audit and remote CI/Security are still required before the integration/deletion claim.
