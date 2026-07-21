#!/usr/bin/env bash
# Run the local API in WSL beside PostgreSQL. The systemd user service owns
# process restarts; readiness failures never cause the launcher to kill a
# healthy process.
set -euo pipefail

ACTION="${1:-start}"
PORT="${2:-8010}"
FE_PORT="${3:-5173}"
UNIT="dramaforge-api"
SCRIPT="$(readlink -f "$0")"
REPO="$(cd "$(dirname "$SCRIPT")/.." && pwd -P)"
VENV="${HOME}/.cache/dramaforge-venv"
PYTHON="${VENV}/bin/python"
LOG_HINT="journalctl --user -u ${UNIT} -n 80 --no-pager"

usage() {
  echo "usage: $0 {start|prepare|stop|status|run} [api-port] [frontend-port]" >&2
}

load_runtime_env() {
  if [[ -f "${REPO}/.env" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%$'\r'}"
      case "$line" in
        ""|\#*) continue ;;
      esac
      key="${line%%=*}"
      value="${line#*=}"
      export "${key}=${value}"
    done < "${REPO}/.env"
  fi

  export APP_ENV="development"
  export DATABASE_URL="postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"
  # Formal P0 path: real MinIO. Memory store is only for APP_ENV=test / pytest.
  unset DRAMA_FORCE_MEMORY_STORE || true
  export DRAMA_FORCE_MEMORY_STORE=""
  export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
  export MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://127.0.0.1:9000}"
  export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
  export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
  export MINIO_BUCKET="${MINIO_BUCKET:-dramaforge}"
  export PYTHONPATH="${REPO}/backend"
  export CORS_ORIGINS="http://localhost:${FE_PORT},http://127.0.0.1:${FE_PORT}"
  export SESSION_SECRET="${SESSION_SECRET:-dev-only-change-me-to-a-long-random-string}"
  export BYOK_FERNET_KEY="${BYOK_FERNET_KEY:-dev-only-fernet-key-replace-in-prod==}"
}

ensure_postgres() {
  if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    return
  fi
  if ! sudo -n pg_ctlcluster 16 main start; then
    echo "PostgreSQL is down and WSL sudo cannot start it." >&2
    exit 1
  fi
  for _ in {1..15}; do
    if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready on 127.0.0.1:5432." >&2
  exit 1
}

ensure_venv() {
  if [[ -x "${PYTHON}" ]]; then
    return
  fi
  python3 -m venv "${VENV}"
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -e "${REPO}/backend"
}

run_migrations() {
  (
    cd "${REPO}/backend"
    "${PYTHON}" -m alembic -c alembic.ini upgrade head
  )
}

wait_for_health() {
  for _ in {1..20}; do
    if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/health" | grep -q '"db":"up"'; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_service() {
  ensure_postgres
  ensure_venv
  load_runtime_env
  run_migrations

  systemctl --user stop "${UNIT}.service" >/dev/null 2>&1 || true
  systemctl --user reset-failed "${UNIT}.service" >/dev/null 2>&1 || true
  systemd-run --user --unit="${UNIT}" --collect \
    --property=Type=exec \
    --property=Restart=on-failure \
    --property=RestartSec=2s \
    --property=KillMode=mixed \
    /usr/bin/bash "${SCRIPT}" run "${PORT}" "${FE_PORT}" >/dev/null

  if ! wait_for_health; then
    echo "API_FAILED ${LOG_HINT}" >&2
    ${LOG_HINT} >&2 || true
    exit 1
  fi
  echo "API_READY port=${PORT} service=${UNIT}"
}

case "${ACTION}" in
  start)
    start_service
    ;;
  prepare)
    ensure_postgres
    ensure_venv
    load_runtime_env
    run_migrations
    echo "DATABASE_READY"
    ;;
  stop)
    systemctl --user stop "${UNIT}.service" >/dev/null 2>&1 || true
    echo "API_STOPPED service=${UNIT}"
    ;;
  status)
    systemctl --user is-active --quiet "${UNIT}.service"
    wait_for_health
    echo "API_READY port=${PORT} service=${UNIT}"
    ;;
  run)
    ensure_venv
    load_runtime_env
    cd "${REPO}/backend"
    exec "${VENV}/bin/uvicorn" app.main:app --host 0.0.0.0 --port "${PORT}"
    ;;
  *)
    usage
    exit 2
    ;;
esac
