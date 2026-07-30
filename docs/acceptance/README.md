# Acceptance Evidence

Generated P0 acceptance evidence is not tracked in this directory. Formal,
commit-bound evidence belongs under `tmp/p0-evidence/<source-commit>/`, which
is ignored by Git and must be retained through the controlled acceptance
process.

`insightface_status_latest.json` is the tracked exception: it records the
latest Docker Compose image smoke baseline only. It is not formal P0 evidence,
is not bound to a source commit, and cannot close a release or P0 Gate.

Do not store credentials, token-bearing download grants, full prompts,
provider responses, or permanent object URLs in repository documentation.
