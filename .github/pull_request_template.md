## Scope

- Task ID:
- Owned paths:
- User-visible result:

## Verification

- [ ] Checks match the change scope; for a PR into `main`, `policy` and all required quality/security checks passed.
- [ ] For a release candidate, `container-gates` passed (backend + PostgreSQL + OpenAPI + frontend + E2E + LiteLLM).
- [ ] No generated formal evidence was committed from a dirty worktree.
- [ ] This is either the release PR `dev -> main`, an optional isolation PR into `dev` (no CI while dev is in fast-development mode), or an urgent `agent/hotfix-* -> main` PR that will be synchronized back to `dev`.

## Approval

- [ ] For `main`, `@zwb2002-yjy` has reviewed and approved this PR; agents do not approve or merge it.
- [ ] For `dev`, integration is within the Owner-authorized task scope; no release approval is inferred.

## Release Evidence

The Docker Compose P0 Gate is run manually before a release or P0 tag. Link the
commit-bound evidence here when this PR is part of a release:

- Source commit:
- Evidence path:
- Gate result:
