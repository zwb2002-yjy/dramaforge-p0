#!/usr/bin/env bash
# P0 operational recovery drill for the WSL formal stack.
#
# This script only writes to an encrypted ignored evidence directory, a new
# PostgreSQL restore database, and a new MinIO restore bucket. It never drops
# or overwrites those targets; operators choose the cleanup window separately.
#
# Required environment:
#   P0_BACKUP_FERNET_KEY       Fernet key for the generated backup archive
#   BYOK_PRIMARY_KEY_VERSION   New encryption version
#   BYOK_KEYRING               Retains old and new version:key entries
#   BYOK_ROTATION_DATABASE_URL Dedicated maintenance DSN with rotation role access
#
# Usage:
#   P0_BACKUP_FERNET_KEY=... BYOK_PRIMARY_KEY_VERSION=v2 BYOK_KEYRING=v1:...,v2:... \
#     bash scripts/p0_ops_drill_wsl.sh
set -euo pipefail

SCRIPT="$(readlink -f "$0" 2>/dev/null || realpath "$0")"
REPO="$(cd "$(dirname "$SCRIPT")/.." && pwd -P)"
VENV="${HOME}/.cache/dramaforge-venv"
PYTHON="${VENV}/bin/python"
API_PORT="${P0_API_PORT:-8010}"
RESTORE_DB_NAME="${P0_RESTORE_DATABASE_NAME:-dramaforge_restore_$(date -u +%Y%m%d%H%M%S)}"
RESTORE_BUCKET="${P0_RESTORE_BUCKET:-dramaforge-restore-$(date -u +%Y%m%d%H%M%S)}"

log() { printf '[p0-ops] %s\n' "$*"; }
fail() { printf '[p0-ops] ERROR: %s\n' "$*" >&2; exit 2; }

require_clean_source() {
  if [[ -n "$(git -C "$REPO" status --porcelain=v1 --untracked-files=normal)" ]]; then
    fail "formal operations evidence requires a clean worktree"
  fi
  SOURCE_COMMIT="$(git -C "$REPO" rev-parse HEAD)"
  EVIDENCE_DIR="$REPO/tmp/p0-evidence/$SOURCE_COMMIT/ops"
  mkdir -p "$EVIDENCE_DIR"
}

load_formal_env() {
  if [[ -f "$REPO/.env" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%$'\r'}"
      case "$line" in
        ""|\#*) continue ;;
      esac
      key="${line%%=*}"
      value="${line#*=}"
      [[ "$key" == "DRAMA_FORCE_MEMORY_STORE" ]] && continue
      case "$key" in
        P0_BACKUP_FERNET_KEY|BYOK_PRIMARY_KEY_VERSION|BYOK_KEYRING|BYOK_ROTATION_DATABASE_URL)
          [[ -n "${!key:-}" ]] && continue
          ;;
      esac
      export "${key}=${value}" 2>/dev/null || true
    done < "$REPO/.env"
  fi
  export APP_ENV="development"
  export DATABASE_URL="postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"
  export MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://127.0.0.1:9000}"
  export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
  export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
  export MINIO_BUCKET="${MINIO_BUCKET:-dramaforge}"
  export MINIO_REGION="${MINIO_REGION:-us-east-1}"
  export PYTHONPATH="$REPO/backend"
  unset DRAMA_FORCE_MEMORY_STORE || true
}

validate_preconditions() {
  [[ -x "$PYTHON" ]] || fail "formal venv missing: $PYTHON"
  [[ -n "${P0_BACKUP_FERNET_KEY:-}" ]] || fail "P0_BACKUP_FERNET_KEY is required"
  [[ -n "${BYOK_PRIMARY_KEY_VERSION:-}" ]] || fail "BYOK_PRIMARY_KEY_VERSION is required"
  [[ -n "${BYOK_KEYRING:-}" ]] || fail "BYOK_KEYRING must retain old and new keys"
  [[ -n "${BYOK_ROTATION_DATABASE_URL:-}" ]] || fail "BYOK_ROTATION_DATABASE_URL is required"
  [[ "$BYOK_KEYRING" == *,* ]] || fail "BYOK_KEYRING must include at least old and new versions"
  [[ "$RESTORE_DB_NAME" =~ ^[a-zA-Z0-9_]+$ ]] || fail "restore database name has unsafe characters"
  [[ "$RESTORE_DB_NAME" != "dramaforge" ]] || fail "restore database must not be dramaforge"
  [[ "$RESTORE_BUCKET" != "$MINIO_BUCKET" ]] || fail "restore bucket must differ from source bucket"
}

check_stack() {
  bash "$REPO/scripts/start_p0_wsl_stack.sh" status "$API_PORT" >/dev/null
  HEALTH="$(curl -fsS --max-time 10 "http://127.0.0.1:${API_PORT}/health")" || fail "formal API health check failed"
  API_COMMIT="$(printf '%s' "$HEALTH" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("source_commit", ""))')"
  [[ "$API_COMMIT" == "$SOURCE_COMMIT" ]] || fail "API source commit does not match the clean worktree"
}

create_restore_database() {
  local admin_url="postgresql://dramaforge:dramaforge@127.0.0.1:5432/postgres"
  if psql "$admin_url" -Atqc "SELECT 1 FROM pg_database WHERE datname = '$RESTORE_DB_NAME'" | grep -qx 1; then
    fail "restore database already exists: $RESTORE_DB_NAME"
  fi
  createdb --maintenance-db="$admin_url" "$RESTORE_DB_NAME"
}

require_real_rotation() {
  local rotation_report="$1"
  local reencrypted
  reencrypted="$(printf '%s' "$rotation_report" | "$PYTHON" -c '
import json
import sys

report = json.load(sys.stdin)
value = report.get("reencrypted")
if type(value) is not int:
    raise SystemExit("rotation report is missing an integer reencrypted count")
print(value)
')" || fail "rotation report is invalid"
  (( reencrypted > 0 )) || fail "BYOK rotation drill requires at least one real credential re-encryption"
}

write_report() {
  local backup_report="$1"
  local restore_report="$2"
  local rotation_report="$3"
  "$PYTHON" - "$EVIDENCE_DIR/ops_drill.json" "$SOURCE_COMMIT" "$RESTORE_DB_NAME" "$RESTORE_BUCKET" \
    "$backup_report" "$restore_report" "$rotation_report" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

out, commit, database, bucket, backup, restore, rotation = sys.argv[1:]
report = {
    "ok": True,
    "source_commit": commit,
    "completed_at_utc": datetime.now(UTC).isoformat(),
    "backup": json.loads(backup),
    "restore": json.loads(restore),
    "rotation": json.loads(rotation),
    "restore_database": database,
    "restore_bucket": bucket,
    "cleanup": "not performed; isolated restore targets remain for inspection",
}
Path(out).write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
PY
}

main() {
  require_clean_source
  load_formal_env
  validate_preconditions
  check_stack
  create_restore_database

  local archive="$EVIDENCE_DIR/backup.enc"
  local backup_report
  local restore_report
  local rotation_report
  backup_report="$(cd "$REPO" && "$PYTHON" scripts/p0_backup_restore.py backup --out "$archive")"
  restore_report="$(cd "$REPO" && "$PYTHON" scripts/p0_backup_restore.py restore-verify \
    --archive "$archive" \
    --restore-database-url "postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/$RESTORE_DB_NAME" \
    --restore-bucket "$RESTORE_BUCKET")"
  rotation_report="$(cd "$REPO" && "$PYTHON" scripts/rotate_byok_keys.py \
    --actor-label "p0-wsl-rotation-drill")"
  require_real_rotation "$rotation_report"
  write_report "$backup_report" "$restore_report" "$rotation_report"
  log "completed evidence=$EVIDENCE_DIR/ops_drill.json"
  log "isolated restore database=$RESTORE_DB_NAME bucket=$RESTORE_BUCKET (not deleted)"
}

main "$@"
