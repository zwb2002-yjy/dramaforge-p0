# P0 Docker Compose Operations Drill

Run this only from a clean candidate commit after the Compose stack is healthy.
The drill creates an encrypted PostgreSQL plus MinIO backup, restores it into
an isolated database and bucket, and records a metadata-only BYOK rotation
result below `tmp/p0-evidence/<commit>/ops/`.

## Preconditions

```powershell
docker compose up -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8080/health
```

Use a secret-manager supplied backup key and retained BYOK keyring. Do not put
these values in shell history, evidence, or tracked configuration. The
rotation login must be granted `dramaforge_byok_rotation` and must not be the
API or Worker login.

The release topology intentionally does not publish PostgreSQL or MinIO to the
host. Run the backup tool in the short-lived maintenance profile, which uses
the migration/admin database account and writes only to the ignored `tmp/`
directory:

```powershell
docker compose --profile maintenance run --rm maintenance `
  backup --out /workspace/tmp/p0-evidence/<commit>/ops/backup.enc
```

Create an isolated restore database and bucket first, then use the same
maintenance container for `restore-verify`. Never point the restore URL or
bucket at the source names.

## Required Evidence

The backup and restore process must prove all of the following:

- The candidate source is clean and the API `source_commit` matches it.
- The restore database and MinIO bucket are new, isolated targets.
- The encrypted archive can be read and its object checksums match.
- A real BYOK rotation re-encrypts at least one credential without storing
  plaintext, ciphertext, provider responses, or keys in the report.

## Real Browser Exercise

After explicit Provider-cost approval, run the browser proof against Compose:

```powershell
$env:P0_REAL_UI = "1"
$env:DRAMAFORGE_API_URL = "http://127.0.0.1:8080"
cd frontend
npm run test:e2e -- --grep "P0 real 10 Shot browser proof"
```

Run the Section 3.1 gate only when the browser report, formal API proof, face
calibration report, and operations evidence bind to the same candidate commit.
