# V1-D0-RUNTIME-BASELINE-20260909

Status: IN_PROGRESS. Work package: D0 of the Owner-authorized D0–D8 revision.

## Authority and outcome

The Owner answered “是” to implementing D0–D8 and making the full director-off
empty-project-to-film path mandatory. Sources are registered in the seven-plan
README under the September 9 amendment. Preserve the supplied documents verbatim;
this contract records execution, not a competing master plan.

Outcome: reproducible source/dependency baseline, protected existing inputs,
explicit runtime observation status and a separate evidence boundary for D work.

## Current evidence / drift

- Local dev HEAD: `4de7acd14481e262346fb0a4802d7725586194ed`, matching both inputs.
- No tracked modifications before D0. Six existing untracked files are user
  inputs: four root Markdown files and the two WUZHEN task contracts. Preserve
  them unmodified and exclude them from this task's commits.
- Prior R candidate: `adf1b9434f59f7dfacf5819d04a77997244e783e`; evidence candidate:
  `3677430a75bb92a588a5304508eaff02a278bf03`. Prior ledger says ready for Owner
  merge; remote merge/deployment has not been verified in D0.
- `workbench.py` still calls DirectorBusinessCheckpoints before commit;
  `next_action.py` queries production ORM; text transport owns turn advancement;
  default workers share director recovery registration. No D implementation exists.
- Backend lock SHA256: `d6c80de22295d132b2a37724110bccfd46c030fbc69ce722f800a71ab60ec054`.
- Frontend lock SHA256: `afae842e4e41dea964b89c931b12800cecafd499bfb4557c852c50a7008f0f7c`.
- Latest numbered migration inspected: `20260908_0060` (Provider cancellation
  recovery), following `0059`; Alembic head verification remains required before
  migration work. An initial partial AST probe missed unannotated revisions and
  is not accepted as a migration graph verification.
- Docker API inspection failed: Linux engine named pipe absent. Running container
  identity and in-flight Turn/NodeRun counts are UNOBSERVED, not zero. Do not
  migrate, restart, cancel or clean existing workloads on this evidence.
- Historical worktrees and open ledger entries are retained; their records do
  not establish that their processes are currently live.
- Lifecycle STARTED was attempted with the existing control script and rejected
  because the root dev worktree is not clean. Existing untracked Owner inputs
  predate this task. No ledger record was fabricated and no user files removed.
  Contract/evidence retain the actual local progress; formal lifecycle completion
  remains unresolved until the script can represent preserved inputs safely.

## Owned paths and effects

README amendment, `v1-goal/director-runtime-20260909/`, this contract and local
ignored `tmp/v1-d0-20260909/` evidence. No application, API, schema or UI change.
No rewrite of seven-plan source-integrity.json or R completion records.

## Verification and completion

Compare copied document hashes to the Owner originals; freeze lock hashes and
Git baseline in structured evidence; inspect diff and relevant source boundaries.
Record unavailable runtime observations explicitly. Before any live migration,
add actual environment/in-flight inventory; D0 static registration does not
authorize treating an unavailable database as empty. Focused verification is
document/source identity and Git diff checks, with no full product gate for D0.
Formal COMPLETED requires evidence, reviewed scoped commit and ledger entry.

## Subsequent environment observations

Docker Desktop was started for isolated validation. The existing application
containers restarted according to their existing policies; their PostgreSQL,
Redis and storage containers were observed exited. No manual restart, migration
or cleanup was performed on those databases. In-flight application data remains
unobserved. D1 uses a separate quality project and disposable test databases.
The local project venv was created with Python 3.12; uv's TLS download failed,
so dependencies were installed by pip from uv's locked export with
`--require-hashes`. Neither lock file was changed. Alembic subsequently verified
the sole head as `20260908_0060`.

The directory compliance command failed on a pre-existing inaccessible
`lib64` link inside historical worktree `p10-v1-revalidation-20260901`.
This is recorded as a failed check, not a pass; that worktree was not modified.

The current bounded directory scanner now ignores inaccessible entries inside
registered external/historical worktrees while continuing to inspect the active
repository. Its final current-source run passes inside the repository quality
image. The historical failure remains recorded above rather than being erased.

## Operations and next dependency

Local implementation and isolated tests are authorized. No fees in D0, no global
install, no shared environment mutation, no merge/deploy or unrelated cleanup.
Prepare D1 contracts after registration. Real Provider validation in D8 requires
an explicit bounded fee plan; previous task fee grants are not silently reused.
