#!/bin/bash
set -euo pipefail
REPO=/mnt/d/调研/dramaforge
VENV="$HOME/.cache/dramaforge-venv"
LOG="$HOME/.cache/dramaforge-api.log"
PIDF="$HOME/.cache/dramaforge-api.pid"
mkdir -p "$HOME/.cache"
sudo pg_ctlcluster 16 main start || true

# kill old by port
if command -v fuser >/dev/null; then fuser -k 8010/tcp 2>/dev/null || true; fi
sleep 1

if [ ! -x "$VENV/bin/uvicorn" ]; then
  python3 -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  pip install -q -U pip
  if [ -f "$REPO/backend/requirements.txt" ]; then pip install -q -r "$REPO/backend/requirements.txt"
  else pip install -q 'fastapi' 'uvicorn[standard]' 'sqlalchemy[asyncio]' asyncpg pydantic pydantic-settings alembic httpx python-multipart 'passlib[bcrypt]' python-jose email-validator greenlet
  fi
fi

# Load repo .env (BYOK) then force product defaults for P0 standard path.
if [ -f "$REPO/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO/.env"
  set +a
fi
# Standard P0: development + live adapters when keys present (not APP_ENV=test).
export APP_ENV="${APP_ENV:-development}"
if [ "$APP_ENV" = "test" ]; then
  echo "WARN: APP_ENV=test forces Fake adapters — override to development for real P0 path"
fi
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge}"
# Prefer real DB host from Windows .env only if reachable; default WSL local PG.
export DATABASE_URL="postgresql+asyncpg://dramaforge:dramaforge@127.0.0.1:5432/dramaforge"
export DRAMA_FORCE_MEMORY_STORE="${DRAMA_FORCE_MEMORY_STORE:-1}"
export TTS_ENABLED="${TTS_ENABLED:-false}"
export SESSION_SECRET="${SESSION_SECRET:-dev-only-change-me-to-a-long-random-string}"
export BYOK_FERNET_KEY="${BYOK_FERNET_KEY:-dev-only-fernet-key-replace-in-prod==}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}"
export PYTHONPATH="$REPO/backend"
export MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://127.0.0.1:9000}"
export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
export MINIO_BUCKET="${MINIO_BUCKET:-dramaforge}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
echo "APP_ENV=$APP_ENV AGNES_ENABLED=${AGNES_ENABLED:-} TEXT_LLM_ENABLED=${TEXT_LLM_ENABLED:-}"

cd "$REPO/backend"
# Fully detach from WSL session (survives script exit)
: >"$LOG"
setsid "$VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8010 >>"$LOG" 2>&1 < /dev/null &
echo $! >"$PIDF"
# wait for listen up to 15s
for i in $(seq 1 15); do
  if curl -sS http://127.0.0.1:8010/health >/tmp/df-health.json 2>/dev/null; then
    echo "PID=$(cat "$PIDF")"
    cat /tmp/df-health.json
    echo
    ss -lntp | grep 8010 || true
    # prove still alive after short wait
    sleep 2
    if kill -0 "$(cat "$PIDF")" 2>/dev/null; then
      echo STILL_ALIVE
      curl -sS http://127.0.0.1:8010/health; echo
      exit 0
    fi
  fi
  sleep 1
done
echo HEALTH_FAIL
tail -50 "$LOG"
exit 1