# GitHub Ruleset

Repository files define CI and ownership, but GitHub branch protection must also be
configured in the private repository settings.

## Required Ruleset

Create a branch ruleset targeting `main` with these rules:

1. Require a pull request before merging.
2. Require one approval.
3. Require review from Code Owners.
4. Dismiss stale approvals when new commits are pushed.
5. Require conversation resolution before merging.
6. Block force pushes and branch deletion.
7. Require these exact status checks:
   - `policy`
   - `backend-static`
   - `backend-unit`
   - `postgres-integration`
   - `frontend`
   - `frontend-smoke`
   - `frontend-smoke-windows`
8. Do not allow repository administrators or automation agents to bypass the ruleset.

Only `@zwb2002-yjy` may provide the required approval and merge. An agent may create or
update a PR, but it must not approve, merge, or record `MERGED` in the local ledger.
After the merge, the user records `MERGED` with `ApprovedBy @zwb2002-yjy`.

## Local Setup

Install the tracked hooks once per clone:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_git_hooks.ps1
```

Create a writable task in an isolated worktree:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\task_worktree.ps1 `
  -Operation create `
  -TaskId example-task `
  -OwnedPaths "backend/app/example;backend/tests/unit/test_example.py"
```

The pre-push hook rejects every direct push to `refs/heads/main`. GitHub remains the
authoritative enforcement point because local hooks can be removed by a user with local
filesystem access. The local `.agent-control/progress.jsonl` ledger is audit data only:
its `approved_by` value is not identity authentication and cannot replace a GitHub review
or the protected-branch merge record.

## Release Gate

Before a release or P0 tag, run the full non-Docker WSL formal proof and section 3.1 Gate
from a clean checkout of the exact candidate commit. Any `FAIL`, `BLOCKED`, dirty source,
or source mismatch prevents `p0_mvp_complete=true`. Generated reports default to
`tmp/p0-evidence/<sha>/formal/` and `tmp/p0-evidence/<sha>/gate/`; do not refresh or
commit tracked `docs/acceptance/*latest.json` files.
