# P0 WSL Operations Drill

Run this only from a clean commit after the WSL formal stack is running. The
drill creates an encrypted PostgreSQL plus MinIO backup, restores it into an
isolated database and bucket, and records a metadata-only BYOK rotation result.
It writes its evidence below `tmp/p0-evidence/<commit>/ops/`, which is ignored
by Git.

The drill is not a substitute for the real Agent/Media/Playwright formal run.
It is one required operational evidence item and must be tied to the same
commit as the formal proof and Section 3.1 gate.

## Preconditions

Start the formal WSL stack from the same clean worktree:

```powershell
wsl -d Ubuntu-24.04 -- bash /mnt/d/调研/dramaforge/scripts/start_p0_wsl_stack.sh start
```

In that WSL shell, create a backup encryption key in the current shell only.
Keep it in the approved secret manager after the drill. Do not put it in a
command history, evidence file, or Git-tracked configuration.

```bash
export P0_BACKUP_FERNET_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

Prepare a retained keyring. Rotation is deliberately two phase: the new
version writes new ciphertext while the prior version remains readable. Use
values supplied by the secret manager, never literal keys in this document.

```bash
export BYOK_PRIMARY_KEY_VERSION=v2
export BYOK_KEYRING="v1:${BYOK_V1_FERNET_KEY},v2:${BYOK_V2_FERNET_KEY}"
```

The credential store must contain at least one real, organization-scoped BYOK
credential before this drill can demonstrate re-encryption. A result with
`scanned: 0` is a configuration check only and does not close the rotation
evidence gate. Current provider adapters still use environment-scoped keys;
do not claim that rotating this store changes those global environment keys.

## Execute

```bash
cd /mnt/d/调研/dramaforge
bash scripts/p0_ops_drill_wsl.sh
```

The script verifies the API source commit, refuses a dirty worktree, creates a
new `dramaforge_restore_<UTC>` database and a distinct MinIO bucket, and leaves
both targets intact. The output file contains checksums, counts, key versions,
and target names, but not backup keys, BYOK plaintext, ciphertext, provider
responses, or permanent URLs.

Inspect `ops_drill.json` and require all of the following before accepting it:

- `ok` is true and `source_commit` is the candidate commit.
- backup and restore results both report `ok: true`.
- the restore database and bucket are different from the formal source.
- rotation's `primary_key_version` is the intended new version and
  `reencrypted` is positive for a real rotation drill.

Only after the report and application reads have been reviewed can the old
version be removed from `BYOK_KEYRING`. Retain the old key until that review is
complete. Cleanup of the isolated restore database and bucket is an explicit
separate operational action.
