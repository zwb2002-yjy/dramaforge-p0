#!/usr/bin/env bash
# Run API inside WSL next to local PostgreSQL (stable localhost DB).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# Prefer Windows-mounted path when launched from /mnt/d
if [ -d "/mnt/d/调研/dramaforge/backend" ]; then
  REPO="/mnt/d/调研/dramaforge"
fi
VENV="${HOME}/.cache/dramaforge-venv"
LOG="${HOME}/.cache/dramaforge-api.log"
PIDF="${HOME}/.cache/dramaforge-api.pid"

sudo pg_ctlcluster 16 main start 2>/dev/null || true

if [ ! -x "${VENV}/bin/uvicorn" ]; then
  if [ -x "${REPO}/backend/.venv/bin/uvicorn" ]; then
    UV="${REPO}/backend/.venv/bin/uvicorn"
  else
    python3 -m venv "${VENV}"
    # shellcheck disable=SC1091
    source "${VENV}/bin/activate"
    pip install -q -e "${REPO}/backend" || pip install -q "uvicorn[standard]" fastapi sqlalchemy asyncpg httpx pydantic pydantic-settings arq redis
    UV="${VENV}/bin/uvicorn"
  fi
else
  UV="${VENV}/bin/uvicorn"
fi

if command -v fuser >/dev/null; then
  fuser -k 8010/tcp 2>/dev/null || true
fi
sleep 1

export APP_ENV=development
export DATABASE_URL=postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge
export DRAMA_FORCE_MEMORY_STORE=1
export PYTHONPATH="${REPO}/backend"
export CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
export SESSION_SECRET="${SESSION_SECRET:-dev-only-change-me-to-a-long-random-string}"
export BYOK_FERNET_KEY="${BYOK_FERNET_KEY:-dev-only-fernet-key-replace-in-prod==}"

# Load optional .env without CRLF breakage
if [ -f "${REPO}/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      ""|\#*) continue ;;
    esac
    key="${line%%=*}"
    val="${line#*=}"
    # shellcheck disable=SC2163
    export "$key=$val" 2>/dev/null || true
  done < "${REPO}/.env"
  # Force runtime-critical after .env
  export APP_ENV=development
  export DATABASE_URL=postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge
  export DRAMA_FORCE_MEMORY_STORE=1
  export PYTHONPATH="${REPO}/backend"
fi

cd "${REPO}/backend"
: > "${LOG}"
nohup "${UV}" app.main:app --host 0.0.0.0 --port 8010 >>"${LOG}" 2>&1 &
echo $! > "${PIDF}"
echo "API_PID=$(cat "${PIDF}") REPO=${REPO} UV=${UV}"

# Lightweight supervisor — keeps API up if provider hang kills worker
SUP="${HOME}/.cache/dramaforge-api-supervisor.pid"
if [ -f "${SUP}" ]; then
  kill "$(cat "${SUP}")" 2>/dev/null || true
fi
nohup bash -c "
  while true; do
    sleep 8
    if ! curl -sf http://127.0.0.1:8010/health >/dev/null 2>&1; then
      sudo pg_ctlcluster 16 main start 2>/dev/null || true
      fuser -k 8010/tcp 2>/dev/null || true
      sleep 1
      cd '${REPO}/backend'
      export APP_ENV=development
      export DATABASE_URL=postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge
      export DRAMA_FORCE_MEMORY_STORE=1
      export PYTHONPATH='${REPO}/backend'
      export CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
      nohup '${UV}' app.main:app --host 0.0.0.0 --port 8010 >>'${LOG}' 2>&1 &
      echo \$! > '${PIDF}'
    fi
  done
" >/dev/null 2>&1 &
echo $! > "${SUP}"

ok=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if body=$(curl -sf http://127.0.0.1:8010/health 2>/dev/null); then
    echo "$body"
    echo API_OK
    ok=1
    break
  fi
  sleep 1
done
if [ "$ok" -eq 1 ]; then
  exit 0
fi
echo API_FAIL
tail -40 "${LOG}"
exit 1
